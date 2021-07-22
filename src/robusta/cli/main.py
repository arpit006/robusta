import os
import subprocess
import time
import uuid
from contextlib import contextmanager
from typing import List, Optional
from zipfile import ZipFile
from kubernetes import config

import typer
import requests

from robusta._version import __version__


app = typer.Typer()

SLACK_INTEGRATION_SERVICE_ADDRESS = os.environ.get(
    "SLACK_INTEGRATION_SERVICE_ADDRESS",
    "https://robusta.dev/integrations/slack/get-token",
)


def get_examples_url(examples_version=None):
    if examples_version is None:
        examples_version = __version__
    return f"https://storage.googleapis.com/robusta-public/{examples_version}/example-playbooks.zip"


def get_runner_url(runner_version=None):
    if runner_version is None:
        runner_version = __version__
    return f"https://gist.githubusercontent.com/robusta-lab/6b809d508dfc3d8d92afc92c7bbbe88e/raw/robusta-{runner_version}.yaml"


CRASHPOD_YAML = "https://gist.githubusercontent.com/robusta-lab/283609047306dc1f05cf59806ade30b6/raw/crashpod.yaml"
PLAYBOOKS_DIR = "playbooks/"


def exec_in_robusta_runner(
    cmd, tries=1, time_between_attempts=10, error_msg="error running cmd"
):
    cmd = [
        "kubectl",
        "exec",
        "-n",
        "robusta",
        "-it",
        "deploy/robusta-runner",
        "--",
        "bash",
        "-c",
        cmd,
    ]
    for _ in range(tries - 1):
        try:
            return subprocess.check_call(cmd)
        except Exception as e:
            typer.echo(f"{error_msg}")
            time.sleep(time_between_attempts)
    return subprocess.check_call(cmd)


def download_file(url, local_path):
    response = requests.get(url)
    response.raise_for_status()
    with open(local_path, "wb") as f:
        f.write(response.content)


def log_title(title, color=None):
    typer.echo("=" * 70)
    typer.secho(title, fg=color)
    typer.echo("=" * 70)


def replace_in_file(path, original, replacement):
    with open(path) as r:
        text = r.read()
        if original not in text:
            raise Exception(
                f"Cannot replace text {original} in file {path} because it was not found"
            )
        text = text.replace(original, replacement)
    with open(path, "w") as w:
        w.write(text)


@contextmanager
def fetch_runner_logs(all_logs=False):
    start = time.time()
    try:
        yield
    finally:
        log_title("Fetching logs...")
        if all_logs:
            subprocess.check_call(
                f"kubectl logs -n robusta deployment/robusta-runner", shell=True
            )
        else:
            subprocess.check_call(
                f"kubectl logs -n robusta deployment/robusta-runner --since={int(time.time() - start + 1)}s",
                shell=True,
            )


def wait_for_slack_api_key(id: str) -> str:
    while True:
        try:
            response_json = requests.get(
                f"{SLACK_INTEGRATION_SERVICE_ADDRESS}?id={id}"
            ).json()
            if response_json["token"]:
                return str(response_json["token"])
            time.sleep(0.5)
        except Exception as e:
            log_title(f"Error getting slack token {e}")


@app.command()
def install(
    slack_api_key: str = None,
    upgrade: bool = typer.Option(
        False,
        help="Only upgrade Robusta's pods, without deploying the default playbooks",
    ),
    url: str = typer.Option(
        None,
        help="Deploy Robusta from a given YAML file/url instead of using the latest version",
    ),
):
    """install robusta into your cluster"""
    filename = "robusta.yaml"
    if url is not None:
        download_file(url, filename)
    else:
        download_file(get_runner_url(), filename)

    if slack_api_key is None and typer.confirm(
        "do you want to configure slack integration? this is HIGHLY recommended.",
        default=True,
    ):
        id = str(uuid.uuid4())
        typer.launch(f"https://robusta.dev/integrations/slack?id={id}")
        slack_api_key = wait_for_slack_api_key(id)

    if slack_api_key is not None:
        replace_in_file(filename, "<SLACK_API_KEY>", slack_api_key.strip())

    print("upgrade is ", upgrade)
    if not upgrade:  # download and deploy playbooks
        examples()

    with fetch_runner_logs(all_logs=True):
        log_title("Installing")
        subprocess.check_call(["kubectl", "apply", "-f", filename])
        log_title("Waiting for resources to be ready")
        ret = subprocess.call(
            [
                "kubectl",
                "rollout",
                "-n",
                "robusta",
                "status",
                "--timeout=2m",
                "deployments/robusta-runner",
            ]
        )
        if ret:
            print(
                "Deployment Description:",
                subprocess.check_output(
                    [
                        "kubectl",
                        "describe",
                        "-n",
                        "robusta",
                        "deployments/robusta-runner",
                    ]
                ),
            )
            print(
                "Replicaset Description:",
                subprocess.check_output(
                    [
                        "kubectl",
                        "describe",
                        "-n",
                        "robusta",
                        "replicaset",
                    ]
                ),
            )
            print(
                "Pod Description:",
                subprocess.check_output(
                    [
                        "kubectl",
                        "describe",
                        "-n",
                        "robusta",
                        "pod",
                    ]
                ),
            )
            print(
                "Node Description:",
                subprocess.check_output(
                    [
                        "kubectl",
                        "describe",
                        "node",
                    ]
                ),
            )
            raise Exception(f"Could not deploy robusta")

        # subprocess.run(["kubectl", "wait", "-n", "robusta", "pods", "--all", "--for", "condition=available"])
        # TODO: if this is an upgrade there can still be pods in the old terminating status and then we will bring
        # logs from the wrong pod...
        time.sleep(5)  # wait an extra second for logs to be written

    if not upgrade:  # download and deploy playbooks
        deploy(PLAYBOOKS_DIR)

    log_title("Installation Done!")
    log_title(
        "In order to see Robusta in action run 'robusta demo'", color=typer.colors.BLUE
    )


@app.command()
def deploy(playbooks_directory: str):
    """deploy playbooks"""
    log_title("Updating playbooks...")
    with fetch_runner_logs():
        subprocess.check_call(
            f"kubectl create configmap -n robusta robusta-config --from-file {playbooks_directory} -o yaml --dry-run | kubectl apply -f -",
            shell=True,
        )
        subprocess.check_call(
            f'kubectl annotate pods -n robusta --all --overwrite "playbooks-last-modified={time.time()}"',
            shell=True,
        )
        time.sleep(
            5
        )  # wait five seconds for the runner to actually reload the playbooks
    log_title("Deployed playbooks!")


@app.command()
def trigger(
    trigger_name: str,
    param: Optional[List[str]] = typer.Argument(
        None,
        help="data to send to playbook (can be used multiple times)",
        metavar="key=value",
    ),
):
    """trigger a manually run playbook"""
    log_title("Triggering playbook...")
    trigger_params = " ".join([f"-F '{p}'" for p in param])
    with fetch_runner_logs():
        cmd = f"curl -X POST -F 'trigger_name={trigger_name}' {trigger_params} http://localhost:5000/api/trigger"
        exec_in_robusta_runner(
            cmd,
            tries=3,
            error_msg="Cannot trigger playbook - usually this means Robusta just started. Will try again",
        )
        typer.echo("\n")
    log_title("Done!")


@app.command()
def examples(
    slack_channel: str = typer.Option(
        None,
        help="Default Slack channel for Robusta",
    ),
    cluster_name: str = typer.Option(
        None,
        help="Unique name for this cluster",
    ),
    use_robusta_ui: bool = typer.Option(
        False,
        help="Use Robusta's ui?",
    ),
    skip_robusta_sink: bool = typer.Option(
        False,
        help="Enable Robusta sink?",
    ),
    skip_new: bool = typer.Option(
        False,
        help="Skip new config replacements?",
    ),
    account_id: str = typer.Option(
        None,
        help="Robusta UI account id",
    ),
    api_key: str = typer.Option(
        None,
        help="Robusta UI api key",
    ),
    url: str = typer.Option(
        None,
        help="Deploy Robusta playbooks from a given url instead of using the latest version",
    ),
):
    """download example playbooks"""
    filename = "example-playbooks.zip"
    if url:
        download_file(url, filename)
    else:
        download_file(get_examples_url(), filename)

    with ZipFile(filename, "r") as zip_file:
        zip_file.extractall()

    if slack_channel is None:
        slack_channel = typer.prompt(
            "which slack channel should I send notifications to?"
        )

    replace_in_file(
        "playbooks/active_playbooks.yaml", "<DEFAULT_SLACK_CHANNEL>", slack_channel
    )

    if cluster_name is None:
        (all_contexts, current_context) = config.list_kube_config_contexts()
        default_name = (
            current_context.get("name")
            if (current_context and current_context.get("name"))
            else ""
        )
        cluster_name = typer.prompt(
            "Please specify a unique name for your cluster or press ENTER to use the default",
            default=default_name,
        )
    # skip_new is used here, temporary, since we don't have the new fields in the released active_playbooks.yaml yet
    # TODO remove on next release
    if not skip_new and cluster_name is not None:
        replace_in_file(
            "playbooks/active_playbooks.yaml", "<CLUSTER_NAME>", cluster_name.strip()
        )

    if not skip_new and (
        use_robusta_ui or typer.confirm("Would you like to use Robusta UI?")
    ):
        if account_id is None:
            account_id = typer.prompt(
                "Please specify your robusta account id",
                default=None,
            )
        if account_id is not None:
            replace_in_file(
                "playbooks/active_playbooks.yaml",
                "<ROBUSTA_ACCOUNT_ID>",
                account_id.strip(),
            )

        if api_key is None:
            api_key = typer.prompt(
                "Please specify your robusta api key",
                default=None,
            )
        if api_key is not None:
            replace_in_file(
                "playbooks/active_playbooks.yaml",
                "<ROBUSTA_API_KEY>",
                api_key.strip(),
            )
        if not skip_robusta_sink:
            replace_in_file(
                "playbooks/active_playbooks.yaml",
                "#<ENABLE_ROBUSTA_SINK>",
                '  - "robusta platform"',
            )

    typer.echo(f"examples downloaded into the {PLAYBOOKS_DIR} directory")


@app.command()
def playground():
    """open a python playground - useful when writing playbooks"""
    exec_in_robusta_runner("socat readline unix-connect:/tmp/manhole-1")


@app.command()
def version():
    """show the version of the local robusta-cli"""
    if __version__ == "0.0.0":
        typer.echo("running with development version from git")
    else:
        typer.echo(f"version {__version__}")


@app.command()
def demo():
    """deliberately deploy a crashing pod to kubernetes so you can test robusta's response"""
    log_title("Deploying a crashing pod to kubernetes...")
    subprocess.check_call(f"kubectl apply -f {CRASHPOD_YAML}", shell=True)
    log_title(
        "In ~30 seconds you should receive a slack notification on a crashing pod"
    )
    time.sleep(40)
    subprocess.check_call(f"kubectl delete -n robusta deployment crashpod", shell=True)
    log_title("Done!")


if __name__ == "__main__":
    app()
