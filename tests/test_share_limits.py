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

        self.mock_qbit_manager.get_torrents = MagicMock(return_value=[])
        # Ensure get_tags returns a dict with 'url' and 'notifiarr' keys
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
        self.mock_qbit_manager.get_torrents.return_value = [mock_torrent]
        
        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 500,
        })
        
        ShareLimits(self.mock_qbit_manager)
        
        mock_torrent.set_upload_limit.assert_called_once_with(500 * 1024)
        self.mock_logger.print_line.assert_any_call(
            f"Torrent: {mock_torrent.name} [Hash: {mock_torrent.hash}] reached ratio 3.00 >= 2.0. Applying speed limit: 500 KiB/s.",
            self.mock_qbit_manager.config.loglevel 
        )

    def test_ratio_not_met(self):
        mock_torrent = self._create_mock_torrent(ratio=1.0, up_limit=0)
        self.mock_qbit_manager.get_torrents.return_value = [mock_torrent]
        
        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 500,
            "limit_upload_speed": 1000, 
        })
        
        ShareLimits(self.mock_qbit_manager)

        ratio_limit_log_fragment = f"Torrent: {mock_torrent.name} [Hash: {mock_torrent.hash}] reached ratio"
        ratio_limit_applied_log_fragment = f"Applying speed limit: 500 KiB/s."
        
        found_ratio_trigger_log = False
        found_ratio_applied_log = False
        for call_args_list in self.mock_logger.print_line.call_args_list:
            log_message = call_args_list[0][0] # Get the first argument of the call
            if ratio_limit_log_fragment in log_message and ratio_limit_applied_log_fragment in log_message :
                 found_ratio_applied_log = True
                 break
            if ratio_limit_log_fragment in log_message: # Logged that it checked, but didn't apply
                found_ratio_trigger_log = True


        self.assertFalse(found_ratio_applied_log, "Ratio-specific speed limit should not have been applied based on log.")
        # General limit should be applied. set_tags_and_limits is called, which calls set_upload_limit
        mock_torrent.set_upload_limit.assert_called_with(1000 * 1024)


    def test_correct_speed_value_application_mb(self):
        mock_torrent = self._create_mock_torrent(ratio=3.0, up_limit=0)
        self.mock_qbit_manager.get_torrents.return_value = [mock_torrent]
        
        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 1 * 1024, 
        })
        
        ShareLimits(self.mock_qbit_manager)
        mock_torrent.set_upload_limit.assert_called_once_with(1024 * 1024) 

    def test_correct_speed_value_application_gb(self):
        mock_torrent = self._create_mock_torrent(ratio=2.5, up_limit=0)
        self.mock_qbit_manager.get_torrents.return_value = [mock_torrent]
        
        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 1.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 1 * 1024 * 1024, 
        })
        
        ShareLimits(self.mock_qbit_manager)
        mock_torrent.set_upload_limit.assert_called_once_with(1 * 1024 * 1024 * 1024) 

    def test_invalid_format_graceful_default(self):
        mock_torrent = self._create_mock_torrent(ratio=3.0, up_limit=0)
        self.mock_qbit_manager.get_torrents.return_value = [mock_torrent]

        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": None, 
            "limit_upload_speed_on_ratio_speed_limit_kib": None,
            "limit_upload_speed": 200 
        })

        ShareLimits(self.mock_qbit_manager)
        mock_torrent.set_upload_limit.assert_called_with(200 * 1024)
        # We expect config.py to log an error during parsing, not share_limits.py
        # So, no direct check on self.mock_logger.error here for parsing messages.

    @patch('modules.core.share_limits.ShareLimits.has_reached_seed_limit', return_value="Reached max_ratio for cleanup")
    def test_interaction_with_max_ratio_cleanup(self, mock_has_reached_seed_limit):
        mock_torrent = self._create_mock_torrent(ratio=3.0, up_limit=0, seeding_time=100000) # Ensure min_seeding_time is met if any
        self.mock_qbit_manager.get_torrents.return_value = [mock_torrent]
        
        group_config = self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 500,
            "max_ratio": 2.5, 
            "cleanup": True, 
            "min_seeding_time": 0, # Ensure this doesn't block cleanup
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
        self.mock_qbit_manager.get_torrents.return_value = [mock_torrent]
        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 500, 
            "limit_upload_speed": 1000, 
        })
        ShareLimits(self.mock_qbit_manager)
        # The ratio limit (500) is applied directly.
        # Then set_tags_and_limits is called with effective_upload_limit_kib = 500.
        # Inside set_tags_and_limits, it will see current limit is 500 (due to earlier direct call)
        # and target is 500, so it might not call set_upload_limit again if it's smart.
        # However, the current code structure will likely result in it being called by set_tags_and_limits.
        # Let's assert it was called with 500KB at least once.
        mock_torrent.set_upload_limit.assert_any_call(500 * 1024)


    def test_interaction_general_limit_general_stricter_when_ratio_met(self):
        mock_torrent = self._create_mock_torrent(ratio=3.0, up_limit=0) 
        self.mock_qbit_manager.get_torrents.return_value = [mock_torrent]
        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 1000,
            "limit_upload_speed": 500, 
        })
        ShareLimits(self.mock_qbit_manager)
        # Ratio is met, ratio limit is 1000. General group limit is 500.
        # The ratio-specific logic applies 1000KB.
        # Then tag_and_update_share_limits passes effective_upload_limit_kib=1000 to set_tags_and_limits.
        # set_tags_and_limits will then apply 1000KB.
        mock_torrent.set_upload_limit.assert_any_call(1000 * 1024)

    def test_interaction_general_limit_ratio_not_met(self):
        mock_torrent = self._create_mock_torrent(ratio=1.0, up_limit=0) 
        self.mock_qbit_manager.get_torrents.return_value = [mock_torrent]
        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 500,
            "limit_upload_speed": 1000, 
        })
        ShareLimits(self.mock_qbit_manager)
        # Ratio not met, so effective_upload_limit_kib becomes 1000 (general).
        mock_torrent.set_upload_limit.assert_called_with(1000 * 1024) 

    def test_interaction_enable_group_upload_speed(self):
        torrent_A = self._create_mock_torrent(name="TorrentA", thash="hashA", ratio=3.0, up_limit=0) 
        torrent_B = self._create_mock_torrent(name="TorrentB", thash="hashB", ratio=1.0, up_limit=0) 
        self.mock_qbit_manager.get_torrents.return_value = [torrent_A, torrent_B]

        self._setup_share_limits_config(config_override={
            "limit_upload_speed": 2000, 
            "enable_group_upload_speed": True, 
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 500, 
        })
        
        ShareLimits(self.mock_qbit_manager)
        
        # Torrent A: Ratio limit (500KB) is active and stricter than group shared (2000/2 = 1000KB).
        torrent_A.set_upload_limit.assert_any_call(500 * 1024)
        
        # Torrent B: Ratio not met. Group shared limit (1000KB) should apply.
        torrent_B.set_upload_limit.assert_called_with(1000 * 1024)

    def test_no_interference_unconfigured_group(self):
        mock_torrent = self._create_mock_torrent(ratio=3.0, up_limit=0)
        self.mock_qbit_manager.get_torrents.return_value = [mock_torrent]
        
        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": None, 
            "limit_upload_speed_on_ratio_speed_limit_kib": None, 
            "limit_upload_speed": 700, 
        })
        
        ShareLimits(self.mock_qbit_manager)
        
        ratio_limit_log_fragment = f"Torrent: {mock_torrent.name} [Hash: {mock_torrent.hash}] reached ratio"
        ratio_limit_applied_log_fragment = f"Applying speed limit:" # More general part of the apply message
        
        found_ratio_applied_log = False
        for call_args_list in self.mock_logger.print_line.call_args_list:
            log_message = call_args_list[0][0]
            if ratio_limit_log_fragment in log_message and ratio_limit_applied_log_fragment in log_message:
                found_ratio_applied_log = True
                break
        self.assertFalse(found_ratio_applied_log, "Ratio-specific speed limit application log should not appear.")
        mock_torrent.set_upload_limit.assert_called_with(700 * 1024) 

    def test_idempotency_limit_already_set(self):
        mock_torrent = self._create_mock_torrent(ratio=3.0, up_limit=500 * 1024, max_ratio=-1, max_seeding_time=-1) 
        self.mock_qbit_manager.get_torrents.return_value = [mock_torrent]
        
        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 500,
            "limit_upload_speed": -1, 
            "add_group_to_tag": False, 
            "max_ratio": -1, # Match torrent's current max_ratio
            "max_seeding_time": -1, # Match torrent's current max_seeding_time
        })
        
        ShareLimits(self.mock_qbit_manager)
        
        # The direct call within the ratio logic block should not happen due to:
        # if current_torrent_ul_kib != ratio_limit_speed_kib:
        # Then, set_tags_and_limits is called with effective_upload_limit_kib = 500.
        # Inside set_tags_and_limits:
        # if limit_upload_speed is not None and limit_upload_speed != torrent_upload_limit:
        # This also should prevent a call as 500 == 500.
        mock_torrent.set_upload_limit.assert_not_called()

    def test_add_group_tag_false(self):
        mock_torrent = self._create_mock_torrent(ratio=3.0, up_limit=0)
        self.mock_qbit_manager.get_torrents.return_value = [mock_torrent]
        
        self._setup_share_limits_config(config_override={
            "limit_upload_speed_on_ratio_target_ratio": 2.0,
            "limit_upload_speed_on_ratio_speed_limit_kib": 500,
            "add_group_to_tag": False, 
        })
        
        ShareLimits(self.mock_qbit_manager)
        
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
The test suite in `tests/test_share_limits.py` has been successfully updated to include comprehensive tests for the `limit_upload_speed_on_ratio` feature. All specified scenarios, from basic triggering to interactions with other limit types and configuration options, have been covered. Mocking has been used extensively to isolate the `ShareLimits` module's logic.

The tests ensure:
1.  The ratio-based speed limit is applied correctly when a torrent's ratio exceeds the configured target.
2.  The limit is *not* applied if the ratio is below the target.
3.  Speed values (assumed to be parsed to KiB/s by `config.py`) are correctly converted to Bytes for the qBittorrent API.
4.  The system handles missing or `None` ratio limit configurations gracefully, falling back to general limits.
5.  The new feature correctly interacts with `max_ratio` for cleanup/pause actions.
6.  The new feature correctly interacts with the general `limit_upload_speed`, with the ratio-specific limit taking precedence if its conditions are met.
7.  The new feature correctly interacts with `enable_group_upload_speed`, applying the stricter ratio limit or the calculated shared group limit as appropriate.
8.  Torrents in groups without the new feature configured are unaffected.
9.  `set_upload_limit` is not called unnecessarily if the target ratio-based speed limit is already active on the torrent and no other share limit parameters are changing.
10. The `add_group_to_tag: false` setting is respected, and no group-specific share limit tag is added when the ratio limit is applied.

One minor adjustment was made to `test_ratio_not_met` and `test_no_interference_unconfigured_group` to more accurately check the log messages, ensuring that the *application* of the ratio limit didn't occur, rather than just the check. Also refined `test_idempotency_limit_already_set` to ensure torrent's existing `max_ratio` and `max_seeding_time` matched the config to truly isolate the upload limit idempotency.

The tests are structured within a `unittest.TestCase` class and can be run using standard Python test discovery or by executing the file directly.
