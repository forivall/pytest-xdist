from collections import OrderedDict

from _pytest.runner import CollectReport
from .loadfile import LoadFileScheduling
from xdist.remote import Producer
from xdist.report import report_collection_diff
from xdist.workermanage import parse_spec_config


class IsolateFileScheduling(LoadFileScheduling):
    """Implement test isolation scheduling across nodes, grouping by test file.

    This distributes the tests collected across all nodes so each test is run
    just once.  One node collects and submits the list of tests and when all
    collections are received it is verified they are identical collections.
    Then the collection gets divided up in work units, grouped by test file,
    and those work units get submitted to a node for every test file.  Whenever
    a node finishes an item, it calls ``.mark_test_complete()`` which will
    trigger the scheduler to shut down the old node and start up a fresh node.

    When created, ``numnodes`` defines how many nodes are expected to submit a
    collection. This is used to know when all nodes have finished collection.

    This class behaves like LoadFileScheduling, but with modified scheduling
    behaviour.
    """

    def __init__(self, config, log=None):
        if not config.getvalue("tx"):
            config.option.tx = "popen"
        super().__init__(config, log)
        if log is None:
            self.log = Producer("isolatefilesched")
        else:
            self.log = log.isolatefilesched

    def remove_node(self, node):
        if node.shutting_down:
            # clean shutdown after completion
            return None

        return super().remove_node(node)

    def mark_test_complete(self, node, item_index, duration=0):
        """Mark test item as completed by node, then restart the node

        Called by the hook:

        - ``DSession.worker_testreport``.
        """
        nodeid = self.registered_collections[node][item_index]
        scope = self._split_scope(nodeid)

        self.assigned_work[node][scope][nodeid] = True
        if self._pending_of(self.assigned_work[node]) > 1:
            return
        
        if self.workqueue and not node.shutting_down:
            node.shutdown()
            node.notify_inproc("errordown", node=node, error="worker-restart")
