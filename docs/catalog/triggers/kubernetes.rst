Kubernetes (API Server)
############################

.. _kubernetes_triggers:

Robusta can run automated actions when Kubernetes resources change.

For example, we can write annotations to Grafana when deployments update:

.. code-block:: yaml

   - triggers:
     - on_deployment_update:
         name_prefix: my-app-name
         namespace_prefix: ns1
         labels_selector: app=my-app
     actions:
     - add_deployment_lines_to_grafana:
         grafana_url: ....

Example triggers
------------------

The following triggers are available for Pods:

* ``on_pod_create``
* ``on_pod_update``
* ``on_pod_delete``
* ``on_pod_all_changes``

The last trigger, ``on_pod_all_changes``, fires when any of the other triggers fires.

Supported resources
---------------------

The following resources are supported.

An example ``on_RESOURCE_create`` trigger is given for each one. The ``update``,
``delete``, and ``all_changes`` triggers are supported as well.

* Pod: on_pod_create
* ReplicaSet: on_replicaset_create
* DaemonSet: on_daemonset_create
* Deployment: on_deployment_create
* StatefulSet: on_statefulset_create
* Service: on_service_create
* Event: on_event_create
* HorizontalPodAutoscaler: on_horizontalpodautoscaler_create
* Node: on_node_create
* ClusterRole: on_clusterrole_create
* ClusterRoleBinding: on_clusterrolebinding_create
* Job: on_job_create
* Namespace: on_namespace_create
* ServiceAccount: on_serviceaccount_create
* PersistentVolume: on_persistentvolume_create

Wildcard triggers
--------------------

The following wildcard triggers will fire for any supported Kubernetes resource:

* on_kubernetes_any_resource_create
* on_kubernetes_any_resource_update
* on_kubernetes_any_resource_delete
* on_kubernetes_any_resource_all_changes

Additional triggers
-----------------------

These triggers fire on very specific events:

.. _on_kubernetes_warning_event:

* on_kubernetes_warning_event - when a Kubernetes event of level WARNING is created or modified


Limiting when kubernetes triggers fire
----------------------------------------

You can limit all the kubernetes triggers with the following filters:

* ``name_prefix`` - Name prefix to match resources.
* ``namespace_prefix`` - Namespace prefix to match resources.
* ``labels_selector`` - Match resources with these labels. The format is: ``label1=value1,label2=value2``. If more than one labels is provided, **all** need to match.
