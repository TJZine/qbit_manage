import unittest
from unittest.mock import MagicMock, patch, call

# Assuming the modules are importable from the root of the project
# For testing, we might need to adjust sys.path or run tests as a module
import sys
import os

# Add project root to sys.path to allow importing modules
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from modules.core.share_limits import ShareLimits
from modules import util # util.logger will be used

class TestShareLimitsRatioSpeed(unittest.TestCase):

    def setUp(self):
        """Set up for each test method."""
        self.mock_qbit_manager = MagicMock()
        self.mock_qbit_manager.config = MagicMock()
        self.mock_qbit_manager.client = MagicMock()
        self.mock_qbit_manager.config.root_dir = "/downloads"
        self.mock_qbit_manager.config.remote_dir = "/downloads_remote"
        self.mock_qbit_manager.config.dry_run = False
        self.mock_qbit_manager.config.loglevel = "INFO" # Explicitly set for assertions
        
        # Mock settings that are accessed directly
        self.mock_qbit_manager.config.settings = {
            "share_limits_filter_completed": True, 
            "share_limits_tag": "~share_limit", 
            "share_limits_min_seeding_time_tag": "MinSeedTimeNotReached",
            "share_limits_min_num_seeds_tag": "MinSeedsNotMet",
            "share_limits_last_active_tag": "LastActiveLimitNotReached",
        }
        self.mock_qbit_manager.config.share_limits_tag = self.mock_qbit_manager.config.settings["share_limits_tag"]
        self.mock_qbit_manager.config.share_limits_custom_tags = []
        self.mock_qbit_manager.config.share_limits_min_seeding_time_tag = self.mock_qbit_manager.config.settings["share_limits_min_seeding_time_tag"]
        self.mock_qbit_manager.config.share_limits_min_num_seeds_tag = self.mock_qbit_manager.config.settings["share_limits_min_num_seeds_tag"]
        self.mock_qbit_manager.config.share_limits_last_active_tag = self.mock_qbit_manager.config.settings["share_limits_last_active_tag"]


        self.original_util_logger = util.logger
        self.mock_logger = MagicMock()
        util.logger = self.mock_logger

        # Default mock for get_torrents, can be overridden in tests
        self.mock_qbit_manager.get_torrents = MagicMock(return_value=[])
        
        self.mock_qbit_manager.get_tags = MagicMock(return_value={'url': 'mock_tracker_url', 'notifiarr': None})
        self.mock_qbit_manager.torrentinfo = {} 

        self.mock_qbit_manager.config.share_limits = {}
        self.mock_qbit_manager.config.send_notifications = MagicMock() 

    def tearDown(self):
        util.logger = self.original_util_logger 

    def _create_mock_torrent(self, name="test_torrent", thash="test_hash_123", ratio=0.0, up_limit=0, seeding_time=0, category="", tags=None, state_enum=None, num_complete=0, last_activity=0, content_path="/downloads/test_torrent", trackers=None, max_ratio=-1, max_seeding_time=-1):
        torrent = MagicMock()
        torrent.name = name
        torrent.hash = thash
        torrent.ratio = ratio
        torrent.up_limit = up_limit 
        torrent.seeding_time = seeding_time 
        torrent.category = category
        torrent.tags = tags if tags is not None else ""
        torrent.state_enum = state_enum if state_enum else MagicMock() 
        torrent.state_enum.is_complete = True 
        torrent.state_enum.is_paused = False 
        torrent.num_complete = num_complete 
        torrent.last_activity = last_activity 
        torrent.content_path = content_path
        torrent.trackers = trackers if trackers is not None else []
        torrent.max_ratio = max_ratio
        torrent.max_seeding_time = max_seeding_time
        
        torrent.set_upload_limit = MagicMock()
        torrent.set_share_limits = MagicMock()
        torrent.add_tags = MagicMock()
        torrent.remove_tags = MagicMock()
        torrent.resume = MagicMock()

        self.mock_qbit_manager.torrentinfo[name] = {"msg": "", "status": 2}
        return torrent

    def _setup_share_limits_config(self, group_name="test_group", config_override=None):
        default_group_config = {
            "priority": 1,
            "limit_upload_speed_on_ratio_target_ratio": None, 
            "limit_upload_speed_on_ratio_speed_limit_kib": None, 
            "limit_upload_speed": -1, 
            "max_ratio": -1, "max_seeding_time": -1, "max_last_active": -1,
            "min_seeding_time": 0, "min_num_seeds": 0, "min_last_active": 0,
            "cleanup": False, "resume_torrent_after_change": True, "add_group_to_tag": True,
            "custom_tag": None, "torrents": [], 
            "include_all_tags": None, "include_any_tags": None, 
            "exclude_all_tags": None, "exclude_any_tags": None, "categories": None,
            "enable_group_upload_speed": False,
        }
        if config_override:
            default_group_config.update(config_override)
        
        self.mock_qbit_manager.config.share_limits = {group_name: default_group_config}
        return default_group_config

    def test_basic_ratio_trigger(self):
        mock_torrent = self._create_mock_torrent(ratio=3.0, up_limit=0)
        
        def mock_get_torrents_logic(*args, **kwargs):
            params = args[0]
            if "torrent_hashes" in params and params["torrent_hashes"] == mock_torrent.hash:
                return [mock_torrent]
            elif "status_filter" in params:
                return [mock_torrent]
            return []
        self.mock_qbit_manager.get_torrents.side_effect = mock_get_torrents_logic
        
        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 500,
        })
        
        ShareLimits(self.mock_qbit_manager)
        
        mock_torrent.set_upload_limit.assert_called_once_with(500 * 1024)
        self.mock_logger.print_line.assert_any_call(
            f"Torrent: {mock_torrent.name} [Hash: {mock_torrent.hash}] reached ratio 3.00 >= 2.0. Target speed limit for this rule: 500 KiB/s.",
            self.mock_qbit_manager.config.loglevel 
        )

    def test_ratio_not_met(self):
        mock_torrent = self._create_mock_torrent(ratio=1.0, up_limit=0)

        def mock_get_torrents_logic(*args, **kwargs):
            params = args[0]
            if "torrent_hashes" in params and params["torrent_hashes"] == mock_torrent.hash:
                return [mock_torrent]
            elif "status_filter" in params:
                return [mock_torrent]
            return []
        self.mock_qbit_manager.get_torrents.side_effect = mock_get_torrents_logic
        
        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 500,
            "limit_upload_speed": 1000, 
        })
        
        ShareLimits(self.mock_qbit_manager)

        ratio_limit_met_log_fragment = f"Torrent: {mock_torrent.name} [Hash: {mock_torrent.hash}] reached ratio"
        # Check that the specific log for APPLYING the ratio limit is NOT present
        ratio_limit_applied_log_fragment = f"Target speed limit for this rule: 500 KiB/s."
        
        found_ratio_applied_log = False
        for call_args_list in self.mock_logger.print_line.call_args_list:
            log_message = call_args_list[0][0] 
            if ratio_limit_met_log_fragment in log_message and ratio_limit_applied_log_fragment in log_message :
                 found_ratio_applied_log = True
                 break
        self.assertFalse(found_ratio_applied_log, "Ratio-specific speed limit rule should not have been logged as met and applying.")
        mock_torrent.set_upload_limit.assert_called_with(1000 * 1024)


    def test_correct_speed_value_application_mb(self):
        mock_torrent = self._create_mock_torrent(ratio=3.0, up_limit=0)
        def mock_get_torrents_logic(*args, **kwargs):
            params = args[0]
            if "torrent_hashes" in params and params["torrent_hashes"] == mock_torrent.hash:
                return [mock_torrent]
            elif "status_filter" in params:
                return [mock_torrent]
            return []
        self.mock_qbit_manager.get_torrents.side_effect = mock_get_torrents_logic
        
        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 1 * 1024, 
        })
        
        ShareLimits(self.mock_qbit_manager)
        mock_torrent.set_upload_limit.assert_called_once_with(1024 * 1024) 

    def test_correct_speed_value_application_gb(self):
        mock_torrent = self._create_mock_torrent(ratio=2.5, up_limit=0)
        def mock_get_torrents_logic(*args, **kwargs):
            params = args[0]
            if "torrent_hashes" in params and params["torrent_hashes"] == mock_torrent.hash:
                return [mock_torrent]
            elif "status_filter" in params:
                return [mock_torrent]
            return []
        self.mock_qbit_manager.get_torrents.side_effect = mock_get_torrents_logic

        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 1.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 1 * 1024 * 1024, 
        })
        
        ShareLimits(self.mock_qbit_manager)
        mock_torrent.set_upload_limit.assert_called_once_with(1 * 1024 * 1024 * 1024) 

    def test_invalid_format_graceful_default(self):
        mock_torrent = self._create_mock_torrent(ratio=3.0, up_limit=0)
        def mock_get_torrents_logic(*args, **kwargs):
            params = args[0]
            if "torrent_hashes" in params and params["torrent_hashes"] == mock_torrent.hash:
                return [mock_torrent]
            elif "status_filter" in params:
                return [mock_torrent]
            return []
        self.mock_qbit_manager.get_torrents.side_effect = mock_get_torrents_logic

        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": None, 
            "limit_upload_speed_on_ratio_speed_limit_kib": None,
            "limit_upload_speed": 200 
        })

        ShareLimits(self.mock_qbit_manager)
        mock_torrent.set_upload_limit.assert_called_with(200 * 1024)

    @patch('modules.core.share_limits.ShareLimits.has_reached_seed_limit', return_value="Reached max_ratio for cleanup")
    def test_interaction_with_max_ratio_cleanup(self, mock_has_reached_seed_limit):
        mock_torrent = self._create_mock_torrent(ratio=3.0, up_limit=0, seeding_time=100000)
        def mock_get_torrents_logic(*args, **kwargs):
            params = args[0]
            if "torrent_hashes" in params and params["torrent_hashes"] == mock_torrent.hash:
                return [mock_torrent]
            elif "status_filter" in params:
                return [mock_torrent]
            return []
        self.mock_qbit_manager.get_torrents.side_effect = mock_get_torrents_logic
        
        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 500,
            "max_ratio": 2.5, 
            "cleanup": True, 
            "min_seeding_time": 0, 
        })
        
        self.mock_qbit_manager.has_cross_seed = MagicMock(return_value=False)
        self.mock_qbit_manager.tor_delete_recycle = MagicMock()

        with patch('os.path.exists', return_value=True): 
            ShareLimits(self.mock_qbit_manager)
        
        mock_torrent.set_upload_limit.assert_any_call(500 * 1024)
        mock_has_reached_seed_limit.assert_called_once()
        self.mock_qbit_manager.tor_delete_recycle.assert_called_once_with(mock_torrent, unittest.mock.ANY)

    def test_interaction_general_limit_ratio_stricter(self):
        mock_torrent = self._create_mock_torrent(ratio=3.0, up_limit=0)
        def mock_get_torrents_logic(*args, **kwargs):
            params = args[0]
            if "torrent_hashes" in params and params["torrent_hashes"] == mock_torrent.hash:
                return [mock_torrent]
            elif "status_filter" in params:
                return [mock_torrent]
            return []
        self.mock_qbit_manager.get_torrents.side_effect = mock_get_torrents_logic

        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 500, 
            "limit_upload_speed": 1000, 
        })
        ShareLimits(self.mock_qbit_manager)
        mock_torrent.set_upload_limit.assert_any_call(500 * 1024)


    def test_interaction_general_limit_general_stricter_when_ratio_met(self):
        mock_torrent = self._create_mock_torrent(ratio=3.0, up_limit=0) 
        def mock_get_torrents_logic(*args, **kwargs):
            params = args[0]
            if "torrent_hashes" in params and params["torrent_hashes"] == mock_torrent.hash:
                return [mock_torrent]
            elif "status_filter" in params:
                return [mock_torrent]
            return []
        self.mock_qbit_manager.get_torrents.side_effect = mock_get_torrents_logic

        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 1000,
            "limit_upload_speed": 500, 
        })
        ShareLimits(self.mock_qbit_manager)
        mock_torrent.set_upload_limit.assert_any_call(1000 * 1024)

    def test_interaction_general_limit_ratio_not_met(self):
        mock_torrent = self._create_mock_torrent(ratio=1.0, up_limit=0) 
        def mock_get_torrents_logic(*args, **kwargs):
            params = args[0]
            if "torrent_hashes" in params and params["torrent_hashes"] == mock_torrent.hash:
                return [mock_torrent]
            elif "status_filter" in params:
                return [mock_torrent]
            return []
        self.mock_qbit_manager.get_torrents.side_effect = mock_get_torrents_logic

        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 500,
            "limit_upload_speed": 1000, 
        })
        ShareLimits(self.mock_qbit_manager)
        mock_torrent.set_upload_limit.assert_called_with(1000 * 1024) 

    def test_interaction_enable_group_upload_speed(self):
        torrent_A = self._create_mock_torrent(name="TorrentA", thash="hashA", ratio=3.0, up_limit=0) 
        torrent_B = self._create_mock_torrent(name="TorrentB", thash="hashB", ratio=1.0, up_limit=0) 
        
        # Define this list here so the side_effect function can close over it
        initial_torrents_list = [torrent_A, torrent_B]

        def mock_get_torrents_logic(*args, **kwargs):
            params = args[0] if args else {} # Handle calls like get_torrents({"status_filter":...})
            if "torrent_hashes" in params:
                thash = params["torrent_hashes"]
                if thash == torrent_A.hash:
                    return [torrent_A]
                if thash == torrent_B.hash:
                    return [torrent_B]
                return [] 
            elif "status_filter" in params:
                return initial_torrents_list 
            return [] 
        self.mock_qbit_manager.get_torrents.side_effect = mock_get_torrents_logic
        
        self._setup_share_limits_config(config_override={
            "limit_upload_speed": 2000, 
            "enable_group_upload_speed": True, 
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 500, 
        })
        
        ShareLimits(self.mock_qbit_manager)
        
        torrent_A.set_upload_limit.assert_any_call(500 * 1024)
        torrent_B.set_upload_limit.assert_called_with(1000 * 1024)

    def test_no_interference_unconfigured_group(self):
        mock_torrent = self._create_mock_torrent(ratio=3.0, up_limit=0)
        def mock_get_torrents_logic(*args, **kwargs):
            params = args[0]
            if "torrent_hashes" in params and params["torrent_hashes"] == mock_torrent.hash:
                return [mock_torrent]
            elif "status_filter" in params:
                return [mock_torrent]
            return []
        self.mock_qbit_manager.get_torrents.side_effect = mock_get_torrents_logic
        
        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": None, 
            "limit_upload_speed_on_ratio_speed_limit_kib": None, 
            "limit_upload_speed": 700, 
        })
        
        ShareLimits(self.mock_qbit_manager)
        
        ratio_limit_met_log_fragment = f"Torrent: {mock_torrent.name} [Hash: {mock_torrent.hash}] reached ratio"
        # Check that the specific log for APPLYING the ratio limit is NOT present
        ratio_limit_target_log_fragment = f"Target speed limit for this rule:"
        
        found_ratio_target_log = False
        for call_args_list in self.mock_logger.print_line.call_args_list:
            log_message = call_args_list[0][0]
            if ratio_limit_met_log_fragment in log_message and ratio_limit_target_log_fragment in log_message:
                found_ratio_target_log = True
                break
        self.assertFalse(found_ratio_target_log, "Ratio-specific speed limit rule should not have been logged as met and applying.")
        mock_torrent.set_upload_limit.assert_called_with(700 * 1024) 

    def test_idempotency_limit_already_set(self):
        mock_torrent = self._create_mock_torrent(ratio=3.0, up_limit=500 * 1024, max_ratio=-1, max_seeding_time=-1) 
        def mock_get_torrents_logic(*args, **kwargs):
            params = args[0]
            if "torrent_hashes" in params and params["torrent_hashes"] == mock_torrent.hash:
                return [mock_torrent]
            elif "status_filter" in params:
                return [mock_torrent]
            return []
        self.mock_qbit_manager.get_torrents.side_effect = mock_get_torrents_logic
        
        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 500,
            "limit_upload_speed": -1, 
            "add_group_to_tag": False, 
            "max_ratio": -1, 
            "max_seeding_time": -1, 
        })
        
        ShareLimits(self.mock_qbit_manager)
        mock_torrent.set_upload_limit.assert_not_called()

    def test_add_group_tag_false(self):
        mock_torrent = self._create_mock_torrent(ratio=3.0, up_limit=0)
        def mock_get_torrents_logic(*args, **kwargs):
            params = args[0]
            if "torrent_hashes" in params and params["torrent_hashes"] == mock_torrent.hash:
                return [mock_torrent]
            elif "status_filter" in params:
                return [mock_torrent]
            return []
        self.mock_qbit_manager.get_torrents.side_effect = mock_get_torrents_logic
        
        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 500,
            "add_group_to_tag": False, 
        })
        
        ShareLimits(self.mock_qbit_manager)
        
        # Ratio limit will be applied, so set_upload_limit is called
        mock_torrent.set_upload_limit.assert_any_call(500*1024)

        tag_prefix_to_avoid = self.mock_qbit_manager.config.settings["share_limits_tag"]
        tag_added = False
        if mock_torrent.add_tags.called:
            for call_arg in mock_torrent.add_tags.call_args_list:
                args, _ = call_arg
                if args and isinstance(args[0], str) and args[0].startswith(tag_prefix_to_avoid):
                    tag_added = True
                    break
        self.assertFalse(tag_added, f"Tag starting with '{tag_prefix_to_avoid}' should not have been added when add_group_to_tag is False.")

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestShareLimitsRatioSpeed)
    runner = unittest.TextTestRunner()
    runner.run(suite)

```

**Reasoning for the Fix:**

The primary issue was that the `self.qbt.get_torrents({"torrent_hashes": t_hash})[0]` call inside `update_share_limits_for_group` was not correctly handled by the generic mock setup for `get_torrents`.

When `get_torrents` was initially mocked with `self.mock_qbit_manager.get_torrents.return_value = [torrent_A, torrent_B]`, this meant *any* call to `get_torrents`, regardless of arguments, would return that full list.
So, when processing `torrent_B` (second in the list), the line `torrent = self.qbt.get_torrents({"torrent_hashes": t_hash})[0]` would execute.
If `t_hash` was `torrent_B.hash`, the mock would *still* return `[torrent_A, torrent_B]`. Then `[0]` would select `torrent_A`.
Subsequent operations intended for `torrent_B` would then incorrectly be applied to `torrent_A` (or rather, the mock object representing `torrent_A` that the `ShareLimits` module now holds a reference to under the variable `torrent`). The original `torrent_B` mock object, which the test case holds and asserts against, would not be modified as expected.

The fix involves changing `self.mock_qbit_manager.get_torrents` to use `side_effect`. This allows for a custom function that inspects the arguments passed to `get_torrents` and returns the appropriate mock torrent object:
*   If called with `{"status_filter": ...}` (initial call), it returns the list `[torrent_A, torrent_B]`.
*   If called with `{"torrent_hashes": torrent_A.hash}`, it returns `[torrent_A]`.
*   If called with `{"torrent_hashes": torrent_B.hash}`, it returns `[torrent_B]`.

This ensures that the re-fetch operation `torrent = self.qbt.get_torrents({"torrent_hashes": t_hash})[0]` correctly assigns the *original* mock object for the torrent being processed to the local `torrent` variable within `update_share_limits_for_group`.

This fix was applied to all tests that involve processing more than one torrent or rely on the re-fetch mechanism, ensuring that the correct mock torrent objects are manipulated and asserted upon.
The log assertion in `test_ratio_not_met` and `test_no_interference_unconfigured_group` was also refined to more accurately reflect the expected logging behavior.
In `test_add_group_tag_false`, added an `assert_any_call` for `set_upload_limit` because the ratio limit *is* applied, the focus of that test is only the tagging.The `test_interaction_enable_group_upload_speed` in `tests/test_share_limits.py` was failing for `torrent_B` because the mock setup for `self.mock_qbit_manager.get_torrents` was too simplistic. It would always return the full list of torrents (`[torrent_A, torrent_B]`) even when the production code attempted to re-fetch a single torrent by its hash using `self.qbt.get_torrents({"torrent_hashes": t_hash})[0]`. This meant that during the processing loop, when `torrent_B` was being processed and then re-fetched by its hash, the `[0]` index might inadvertently reassign `torrent_A` (or a new default mock) to the local `torrent` variable within `update_share_limits_for_group`. Consequently, any subsequent calls to `torrent.set_upload_limit()` would be on the wrong mock object, and the original `torrent_B` mock object (which the test case holds the reference to for assertion) would not register the call.

The fix involved making the `get_torrents` mock more sophisticated using `side_effect`. A helper function `mock_get_torrents_logic` was defined (or an equivalent lambda for simpler, single-torrent tests) that inspects the arguments passed to `get_torrents`.
- If it's the initial call (e.g., with `{"status_filter": ...}`), it returns the list of all mock torrents relevant to the test (`[torrent_A, torrent_B]`).
- If it's a call to re-fetch by hash (e.g., with `{"torrent_hashes": some_hash}`), it returns a list containing only the specific mock torrent that matches that hash.

This ensures that the line `torrent = self.qbt.get_torrents({"torrent_hashes": t_hash})[0]` in `update_share_limits_for_group` always reassigns the *correct, original* mock torrent object to the local `torrent` variable. As a result, methods like `set_upload_limit` are called on the mock object that the test is actually asserting against, leading to the test passing.

This `side_effect` logic was applied to `test_interaction_enable_group_upload_speed` and retroactively to other relevant tests in `tests/test_share_limits.py` to ensure their robustness regarding torrent re-fetching. Minor log assertion refinements were also made in a couple of tests for accuracy.
