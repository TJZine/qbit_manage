import os
from datetime import timedelta
from time import time

from modules import util
from modules.util import is_tag_in_torrent
from modules.webhooks import GROUP_NOTIFICATION_LIMIT

logger = util.logger


class ShareLimits:
    def __init__(self, qbit_manager):
        self.qbt = qbit_manager
        self.config = qbit_manager.config
        self.client = qbit_manager.client
        self.stats_tagged = 0  # counter for the number of share limits changed
        self.stats_deleted = 0  # counter for the number of torrents that \
        # meets the criteria for ratio limit/seed limit for deletion
        self.stats_deleted_contents = 0  # counter for the number of torrents that  \
        # meets the criteria for ratio limit/seed limit for deletion including contents \
        self.status_filter = "completed" if self.config.settings["share_limits_filter_completed"] else "all"

        # dictionary to track the torrent names and content path that meet the deletion criteria
        self.tdel_dict = {}
        self.root_dir = qbit_manager.config.root_dir  # root directory of torrents
        self.remote_dir = qbit_manager.config.remote_dir  # remote directory of torrents
        # configuration of share limits
        self.share_limits_config = qbit_manager.config.share_limits
        self.torrents_updated = []  # list of torrents that have been updated
        # list of torrent hashes that have been checked for share limits
        self.torrent_hash_checked = []
        self.share_limits_tag = qbit_manager.config.share_limits_tag  # tag for share limits
        # All possible custom share limits tags
        self.share_limits_custom_tags = qbit_manager.config.share_limits_custom_tags
        # tag for min seeding time
        self.min_seeding_time_tag = qbit_manager.config.share_limits_min_seeding_time_tag
        # tag for min num seeds
        self.min_num_seeds_tag = qbit_manager.config.share_limits_min_num_seeds_tag
        # tag for last active
        self.last_active_tag = qbit_manager.config.share_limits_last_active_tag
        self.group_tag = None  # tag for the share limit group

        self.update_share_limits()
        self.delete_share_limits_suffix_tag()

    def update_share_limits(self):
        """Updates share limits for torrents based on grouping"""
        logger.separator("Updating Share Limits based on priority", space=False, border=False)
        if self.config.dry_run:
            logger.warning("Share Limits will not be applied with dry_run and could be inaccurate unless manually adding tags.")
        torrent_list = self.qbt.get_torrents({"status_filter": self.status_filter})
        self.assign_torrents_to_group(torrent_list)
        for group_name, group_config in self.share_limits_config.items():
            torrents = group_config["torrents"]
            self.torrents_updated = []
            self.tdel_dict = {}
            group_priority = group_config.get("priority", "Unknown")
            num_torrents = len(torrents) if torrents else 0

            logger.separator(
                f"Updating Share Limits for [Group {group_name}] [Priority {group_priority}] [Torrents ({num_torrents})]",
                space=False,
                border=False,
            )
            if torrents:
                self.update_share_limits_for_group(group_name, group_config, torrents)
                attr = {
                    "function": "share_limits",
                    "title": f"Updating Share Limits for {group_name}. Priority {group_config['priority']}",
                    "body": f"Updated {len(self.torrents_updated)} torrents.",
                    "grouping": group_name,
                    "torrents": self.torrents_updated,
                    "torrent_tag": self.group_tag,
                    "torrent_max_ratio": group_config["max_ratio"],
                    "torrent_max_seeding_time": group_config["max_seeding_time"],
                    "torrent_max_last_active": group_config["max_last_active"],
                    "torrent_min_seeding_time": group_config["min_seeding_time"],
                    "torrent_min_num_seeds": group_config["min_num_seeds"],
                    "torrent_limit_upload_speed": group_config["limit_upload_speed"],
                    "torrent_min_last_active": group_config["min_last_active"],
                }
                if len(self.torrents_updated) > 0:
                    self.config.send_notifications(attr)
                if group_config["cleanup"] and len(self.tdel_dict) > 0:
                    self.cleanup_torrents_for_group(group_name, group_config["priority"])

    def cleanup_torrents_for_group(self, group_name, priority):
        """Deletes torrents that have reached the ratio/seed limit"""
        logger.separator(
            f"Cleaning up torrents that have reached ratio/seed limit for {group_name}. Priority {priority}",
            space=False,
            border=False,
        )
        group_notifications = len(self.tdel_dict) > GROUP_NOTIFICATION_LIMIT
        t_deleted = set()
        t_deleted_and_contents = set()
        for torrent_hash, torrent_dict in self.tdel_dict.items():
            torrent = torrent_dict["torrent"]
            t_name = torrent.name
            t_msg = self.qbt.torrentinfo[t_name]["msg"]
            t_status = self.qbt.torrentinfo[t_name]["status"]
            # Double check that the content path is the same before we delete anything
            if torrent["content_path"].replace(self.root_dir, self.remote_dir) == torrent_dict["content_path"]:
                tracker = self.qbt.get_tags(self.qbt.get_tracker_urls(torrent.trackers))
                body = []
                body += logger.print_line(logger.insert_space(f"Torrent Name: {t_name}", 3), self.config.loglevel)
                body += logger.print_line(logger.insert_space(f"Tracker: {tracker['url']}", 8), self.config.loglevel)
                body += logger.print_line(torrent_dict["body"], self.config.loglevel)
                body += logger.print_line(
                    logger.insert_space("Cleanup: True [Meets Share Limits]", 8),
                    self.config.loglevel,
                )
                attr = {
                    "function": "cleanup_share_limits",
                    "title": "Share limit removal",
                    "grouping": group_name,
                    "torrents": [t_name],
                    "torrent_category": torrent.category,
                    "cleanup": True,
                    "torrent_tracker": tracker["url"],
                    "notifiarr_indexer": tracker["notifiarr"],
                }
                if os.path.exists(torrent["content_path"].replace(self.root_dir, self.remote_dir)):
                    # Checks if any of the original torrents are working
                    if self.qbt.has_cross_seed(torrent) and ("" in t_msg or 2 in t_status):
                        self.stats_deleted += 1
                        attr["torrents_deleted_and_contents"] = False
                        t_deleted.add(t_name)
                        if not self.config.dry_run:
                            self.qbt.tor_delete_recycle(torrent, attr)
                        body += logger.print_line(
                            logger.insert_space("Deleted .torrent but NOT content files. Reason: is cross-seed", 8),
                            self.config.loglevel,
                        )
                    else:
                        self.stats_deleted_contents += 1
                        attr["torrents_deleted_and_contents"] = True
                        t_deleted_and_contents.add(t_name)
                        if not self.config.dry_run:
                            self.qbt.tor_delete_recycle(torrent, attr)
                        body += logger.print_line(
                            logger.insert_space("Deleted .torrent AND content files.", 8), self.config.loglevel
                        )
                else:
                    self.stats_deleted += 1
                    attr["torrents_deleted_and_contents"] = False
                    t_deleted.add(t_name)
                    if not self.config.dry_run:
                        self.qbt.tor_delete_recycle(torrent, attr)
                    body += logger.print_line(
                        logger.insert_space(
                            "Deleted .torrent but NOT content files. Reason: path does not exist [path="
                            + torrent["content_path"].replace(self.root_dir, self.remote_dir)
                            + "].",
                            8,
                        ),
                        self.config.loglevel,
                    )
                attr["body"] = "\n".join(body)
                if not group_notifications:
                    self.config.send_notifications(attr)
        if group_notifications:
            if t_deleted:
                attr = {
                    "function": "cleanup_share_limits",
                    "title": "Share limit removal - Deleted .torrent but NOT content files.",
                    "body": f"Deleted {self.stats_deleted} .torrents but NOT content files.",
                    "grouping": group_name,
                    "torrents": list(t_deleted),
                    "torrent_category": None,
                    "cleanup": True,
                    "torrent_tracker": None,
                    "notifiarr_indexer": None,
                    "torrents_deleted_and_contents": False,
                }
                self.config.send_notifications(attr)
            if t_deleted_and_contents:
                attr = {
                    "function": "cleanup_share_limits",
                    "title": "Share limit removal - Deleted .torrent AND content files.",
                    "body": f"Deleted {self.stats_deleted_contents} .torrents AND content files.",
                    "grouping": group_name,
                    "torrents": list(t_deleted_and_contents),
                    "torrent_category": None,
                    "cleanup": True,
                    "torrent_tracker": None,
                    "notifiarr_indexer": None,
                    "torrents_deleted_and_contents": True,
                }
                self.config.send_notifications(attr)

    def update_share_limits_for_group(self, group_name, group_config, torrents):
        """Updates share limits for torrents in a group"""
        group_upload_speed = group_config["limit_upload_speed"]
        # Get ratio-specific speed limit settings from config
        ratio_limit_target_ratio = group_config.get("limit_upload_speed_on_ratio_target_ratio")
        ratio_limit_speed_kib = group_config.get("limit_upload_speed_on_ratio_speed_limit_kib")

        for torrent in torrents:
            t_name = torrent.name
            t_hash = torrent.hash
            ratio_speed_limit_active_and_applied = False
            effective_upload_limit_kib = group_config["limit_upload_speed"]

            # New logic for limit_upload_speed_on_ratio
            if ratio_limit_target_ratio is not None and ratio_limit_speed_kib is not None:
                current_ratio = torrent.ratio
                logger.trace(
                    f"Torrent: {t_name} [Hash: {t_hash}] - Checking ratio-based speed limit. "
                    f"Current Ratio: {current_ratio:.2f}, Target Ratio: {ratio_limit_target_ratio}, "
                    f"Speed Limit if Met: {ratio_limit_speed_kib} KiB/s"
                )
                if current_ratio >= ratio_limit_target_ratio:
                    current_torrent_ul_kib = round(torrent.up_limit / 1024) if torrent.up_limit > 0 else -1
                    # Determine if ratio rule implies a change, but don't apply it yet.
                    # The actual application will happen in set_tags_and_limits.
                    # Log that the ratio condition is met.
                    logger.print_line("DIAGNOSTIC_LOG_FOR_RATIO_TRIGGER", "INFO")
                    effective_upload_limit_kib = ratio_limit_speed_kib
                    ratio_speed_limit_active_and_applied = True # Flag that this rule's speed should be considered
                    # No direct torrent.set_upload_limit() call here.
                    # We still need to increment stats if this represents a change that will be applied later.
                    # This will be handled by check_limit_upload_speed comparison later.
                else: # Ratio not met, ratio rule does not apply for speed setting.
                    logger.trace(
                        f"Torrent: {t_name} [Hash: {t_hash}] ratio {current_ratio:.2f} < {ratio_limit_target_ratio}. "
                        f"Ratio-specific speed limit not applicable."
                    )
                    # effective_upload_limit_kib remains group_config["limit_upload_speed"] as initialized earlier
                    # ratio_speed_limit_active_and_applied remains False

            # Determine the final effective upload speed to check against torrent's current limit
            if not ratio_speed_limit_active_and_applied: # If ratio rule wasn't met or not configured
                general_group_ul_config = group_config["limit_upload_speed"]
                if general_group_ul_config <= 0:
                    effective_upload_limit_kib = -1 # Unlimited
                elif group_config["enable_group_upload_speed"] and len(torrents) > 0:
                    # group_upload_speed is the original 'limit_upload_speed' from config before any per-torrent division
                    effective_upload_limit_kib = round(group_upload_speed / len(torrents))
                else:
                    effective_upload_limit_kib = general_group_ul_config
            # else: effective_upload_limit_kib is already set by the ratio rule logic above

            # Original logic continues below, using the now finalized effective_upload_limit_kib
            if group_config["add_group_to_tag"]:
                if group_config["custom_tag"]:
                    self.group_tag = group_config["custom_tag"]
                else:
                    self.group_tag = f"{self.share_limits_tag}_{group_config['priority']}.{group_name}"
            else:
                self.group_tag = None
            tracker = self.qbt.get_tags(self.qbt.get_tracker_urls(torrent.trackers))
            check_max_ratio = group_config["max_ratio"] != torrent.max_ratio
            check_max_seeding_time = group_config["max_seeding_time"] != torrent.max_seeding_time
            
            torrent_current_actual_ul_kib = round(torrent.up_limit / 1024) if torrent.up_limit > 0 else -1
            check_limit_upload_speed = effective_upload_limit_kib != torrent_current_actual_ul_kib
            
            # If check_limit_upload_speed is true, it means either the ratio rule or general rules
            # determined a speed that's different from the torrent's current speed.
            # This is one of the conditions that might lead to calling tag_and_update_share_limits_for_torrent.
            # The stats_tagged and torrents_updated will be incremented inside the main conditional block below
            # if any of the conditions (max_ratio, max_seeding_time, check_limit_upload_speed, tagging) are met.
            
            hash_not_prev_checked = t_hash not in self.torrent_hash_checked

            if self.group_tag:
                if group_config["custom_tag"] and not is_tag_in_torrent(self.group_tag, torrent.tags):
                    share_limits_not_yet_tagged = True
                elif not group_config["custom_tag"] and not is_tag_in_torrent(self.group_tag, torrent.tags, exact=False):
                    share_limits_not_yet_tagged = True
                else:
                    share_limits_not_yet_tagged = False

                # Default assume no multiple share limits tag
                check_multiple_share_limits_tag = False

                # Check if any of the previous share limits custom tags are there
                for custom_tag in self.share_limits_custom_tags:
                    if custom_tag != self.group_tag and is_tag_in_torrent(custom_tag, torrent.tags):
                        check_multiple_share_limits_tag = True
                        break
                # Check if there are any other share limits tags in the torrent
                if group_config["custom_tag"] and len(is_tag_in_torrent(self.share_limits_tag, torrent.tags, exact=False)) > 0:
                    check_multiple_share_limits_tag = True
                elif (
                    not group_config["custom_tag"]
                    and len(is_tag_in_torrent(self.share_limits_tag, torrent.tags, exact=False)) > 1
                ):
                    check_multiple_share_limits_tag = True
            else:
                share_limits_not_yet_tagged = False
                check_multiple_share_limits_tag = False

            logger.trace(f"Torrent: {t_name} [Hash: {t_hash}]")
            logger.trace(f"Torrent Category: {torrent.category}")
            logger.trace(f"Torrent Tags: {torrent.tags}")
            logger.trace(f"Grouping: {group_name}")
            logger.trace(f"Config Max Ratio vs Torrent Max Ratio:{group_config['max_ratio']} vs {torrent.max_ratio}")
            logger.trace(f"check_max_ratio: {check_max_ratio}")
            logger.trace(
                "Config Max Seeding Time vs Torrent Max Seeding Time (minutes): "
                f"{group_config['max_seeding_time']} vs {torrent.max_seeding_time}"
            )
            logger.trace(
                "Config Max Seeding Time vs Torrent Current Seeding Time (minutes): "
                f"({group_config['max_seeding_time']} vs {torrent.seeding_time / 60}) "
                f"{str(timedelta(minutes=group_config['max_seeding_time']))} vs {str(timedelta(seconds=torrent.seeding_time))}"
            )
            logger.trace(
                "Config Min Seeding Time vs Torrent Current Seeding Time (minutes): "
                f"({group_config['min_seeding_time']} vs {torrent.seeding_time / 60}) "
                f"{str(timedelta(minutes=group_config['min_seeding_time']))} vs {str(timedelta(seconds=torrent.seeding_time))}"
            )
            logger.trace(f"Config Min Num Seeds vs Torrent Num Seeds: {group_config['min_num_seeds']} vs {torrent.num_complete}")
            logger.trace(f"check_max_seeding_time: {check_max_seeding_time}")
            logger.trace(
                f"Effective Limit Upload Speed vs Torrent Current Actual Upload Speed: "
                f"{effective_upload_limit_kib} KiB/s vs {torrent_current_actual_ul_kib} KiB/s"
            )
            logger.trace(f"check_limit_upload_speed: {check_limit_upload_speed}") # This now reflects the effective speed
            logger.trace(f"hash_not_prev_checked: {hash_not_prev_checked}")
            logger.trace(f"share_limits_not_yet_tagged: {share_limits_not_yet_tagged}")
            logger.trace(
                f"check_multiple_share_limits_tag: {is_tag_in_torrent(self.share_limits_tag, torrent.tags, exact=False)}"
            )

            tor_reached_seed_limit = self.has_reached_seed_limit(
                torrent=torrent,
                max_ratio=group_config["max_ratio"],
                max_seeding_time=group_config["max_seeding_time"],
                max_last_active=group_config["max_last_active"],
                min_seeding_time=group_config["min_seeding_time"],
                min_num_seeds=group_config["min_num_seeds"],
                min_last_active=group_config["min_last_active"],
                resume_torrent=group_config["resume_torrent_after_change"],
                tracker=tracker["url"],
            )
            # Get updated torrent after checking if the torrent has reached seed limits
            torrent = self.qbt.get_torrents({"torrent_hashes": t_hash})[0]
            if (
                check_max_ratio
                or check_max_seeding_time
                or check_limit_upload_speed
                or share_limits_not_yet_tagged
                or check_multiple_share_limits_tag
                    # or ratio_speed_limit_active_and_applied # This was part of the OR condition,
                    # but now it's implicitly handled by check_limit_upload_speed if the ratio rule
                    # implies a speed different from the current torrent speed.
                    # The main point is that if check_limit_upload_speed is true, something needs to be done.
            ) and hash_not_prev_checked:
                # This large conditional block determines if we need to call tag_and_update_share_limits_for_torrent
                # which in turn calls set_tags_and_limits (the single point for API calls).
                # A change in max_ratio, max_seeding_time, the need to tag/re-tag,
                # or a required change in upload speed (check_limit_upload_speed)
                # should trigger this.
                
                # Conditions for calling the update logic:
                # 1. Torrent is not under a special "minimums not met" tag.
                # 2. OR tags need updating (share_limits_not_yet_tagged or check_multiple_share_limits_tag).
                # 3. AND (one of the main share parameters changed OR upload speed needs changing OR tags need updating).
                # This logic seems mostly correct, but the printing and stat incrementing needs care.

                if (
                    not is_tag_in_torrent(self.min_seeding_time_tag, torrent.tags) and
                    not is_tag_in_torrent(self.min_num_seeds_tag, torrent.tags) and
                    not is_tag_in_torrent(self.last_active_tag, torrent.tags)
                   ) or share_limits_not_yet_tagged or check_multiple_share_limits_tag:
                    # This torrent is eligible for normal share limit processing or needs tagging.

                    # Log initial info only once if we are indeed going to make changes or tag.
                    logger.print_line(logger.insert_space(f"Torrent Name: {t_name}", 3), self.config.loglevel)
                    logger.print_line(logger.insert_space(f"Tracker: {tracker['url']}", 8), self.config.loglevel)
                    
                    if self.group_tag and (share_limits_not_yet_tagged or check_multiple_share_limits_tag):
                         logger.print_line(logger.insert_space(f"Applying Tag: {self.group_tag}", 8), self.config.loglevel)

                    self.tag_and_update_share_limits_for_torrent(torrent, group_config, effective_upload_limit_kib)
                    
                    # Increment stats if any actual change was made by set_tags_and_limits or if tags were added/removed.
                    # set_tags_and_limits returns a body list of changes.
                    # We can use its output or rely on the initial checks.
                    # For simplicity, if we entered this block due to a needed change, count it.
                    self.stats_tagged += 1
                    if t_name not in self.torrents_updated:
                        self.torrents_updated.append(t_name)
            
            # Cleanup torrents if the torrent meets the criteria for deletion and cleanup is enabled
            if group_config["cleanup"]:
                if tor_reached_seed_limit:
                    if t_hash not in self.tdel_dict:
                        self.tdel_dict[t_hash] = {}
                    self.tdel_dict[t_hash]["torrent"] = torrent
                    self.tdel_dict[t_hash]["content_path"] = torrent["content_path"].replace(self.root_dir, self.remote_dir)
                    self.tdel_dict[t_hash]["body"] = tor_reached_seed_limit
            self.torrent_hash_checked.append(t_hash)

    def tag_and_update_share_limits_for_torrent(self, torrent, group_config, current_effective_upload_limit_kib):
        """Removes previous share limits tag, updates tag and share limits for a torrent, and resumes the torrent"""
        # Remove previous share_limits tag
        if not self.config.dry_run:
            # Remove general share limit tags if group_tag is being applied or if custom_tag logic needs it
            if self.group_tag:
                tag_to_remove = is_tag_in_torrent(self.share_limits_tag, torrent.tags, exact=False)
                if tag_to_remove:
                    # Ensure not to remove the self.group_tag if it's a general prefix tag that matches
                    tags_make_list = util.get_list(tag_to_remove)
                    for t_rem in tags_make_list:
                         if self.group_tag and t_rem.startswith(self.share_limits_tag) and t_rem != self.group_tag:
                            torrent.remove_tags(t_rem)
                         # If group_tag is not defined (add_group_to_tag is false), remove all general share limit tags
                         elif not self.group_tag and t_rem.startswith(self.share_limits_tag):
                            torrent.remove_tags(t_rem)


            # Remove other custom tags if the current group_tag is a custom_tag or if no group_tag is set (to clean up old custom tags)
            for custom_tag_iter in self.share_limits_custom_tags:
                if is_tag_in_torrent(custom_tag_iter, torrent.tags):
                    if self.group_tag == custom_tag_iter: # current group's tag is this custom_tag, skip removal
                        continue
                    # If current group_tag is different OR if add_group_to_tag is false (no current group tag)
                    # then this custom_tag_iter is from a different group or an old one, so remove it.
                    if not self.group_tag or (self.group_tag and self.group_tag != custom_tag_iter) :
                        torrent.remove_tags(custom_tag_iter)
        
        # Will tag the torrent with the group name if add_group_to_tag is True and set the share limits
        self.set_tags_and_limits(
            torrent=torrent,
            max_ratio=group_config["max_ratio"],
            max_seeding_time=group_config["max_seeding_time"],
            limit_upload_speed=current_effective_upload_limit_kib, # Use the passed effective speed limit
            tags=self.group_tag, # self.group_tag can be None if add_group_to_tag is False
        )
        # Resume torrent if it was paused now that the share limit has changed
        # Ensure torrent is not paused due to min_seeding_time_tag etc.
        if torrent.state_enum.is_paused and group_config["resume_torrent_after_change"]:
            if not (is_tag_in_torrent(self.min_seeding_time_tag, torrent.tags) or
                    is_tag_in_torrent(self.min_num_seeds_tag, torrent.tags) or
                    is_tag_in_torrent(self.last_active_tag, torrent.tags)):
                if not self.config.dry_run:
                    torrent.resume()
                logger.print_line(
                    f"Resuming torrent {torrent.name} after general share limit update.", self.config.loglevel
                )


    def assign_torrents_to_group(self, torrent_list):
        """Assign torrents to a share limit group based on its tags and category"""
        logger.info("Assigning torrents to share limit groups...")
        for torrent in torrent_list:
            tags = util.get_list(torrent.tags)
            category = torrent.category or ""
            grouping = self.get_share_limit_group(tags, category)
            logger.trace(f"Torrent: {torrent.name} [Hash: {torrent.hash}] - Share Limit Group: {grouping}")
            if grouping:
                self.share_limits_config[grouping]["torrents"].append(torrent)

    def get_share_limit_group(self, tags, category):
        """Get the share limit group based on the tags and category of the torrent"""
        for group_name, group_config in self.share_limits_config.items():
            check_tags = self.check_tags(
                tags=tags,
                include_all_tags=group_config["include_all_tags"],
                include_any_tags=group_config["include_any_tags"],
                exclude_all_tags=group_config["exclude_all_tags"],
                exclude_any_tags=group_config["exclude_any_tags"],
            )
            check_category = self.check_category(category, group_config["categories"])

            if check_tags and check_category:
                return group_name
        return None

    def check_tags(self, tags, include_all_tags=set(), include_any_tags=set(), exclude_all_tags=set(), exclude_any_tags=set()):
        """Check if the torrent has the required tags"""
        tags_set = set(tags)
        if include_all_tags:
            if not set(include_all_tags).issubset(tags_set):
                return False
        if include_any_tags:
            if not set(include_any_tags).intersection(tags_set):
                return False
        if exclude_all_tags:
            if set(exclude_all_tags).issubset(tags_set):
                return False
        if exclude_any_tags:
            if set(exclude_any_tags).intersection(tags_set):
                return False
        return True

    def check_category(self, category, categories):
        """Check if the torrent has the required category"""
        if categories:
            if category not in categories:
                return False
        return True

    def set_tags_and_limits(self, torrent, max_ratio, max_seeding_time, limit_upload_speed=None, tags=None, do_print=True):
        """Set tags and limits for a torrent"""
        body = []
        if limit_upload_speed is not None:
            if limit_upload_speed != -1:
                msg = logger.insert_space(f"Limit UL Speed: {limit_upload_speed} kB/s", 1)
                body.append(msg)
        if max_ratio is not None or max_seeding_time is not None:
            if max_ratio == -2 and max_seeding_time == -2:
                msg = logger.insert_space("Share Limit: Use Global Share Limit", 4)
                body.append(msg)
            elif max_ratio == -1 and max_seeding_time == -1:
                msg = logger.insert_space("Share Limit: Set No Share Limit", 4)
                body.append(msg)
            else:
                if max_ratio != torrent.max_ratio and (max_seeding_time is None or max_seeding_time < 0):
                    msg = logger.insert_space(f"Share Limit: Max Ratio = {max_ratio}", 4)
                    body.append(msg)
                elif max_seeding_time != torrent.max_seeding_time and (max_ratio is None or max_ratio < 0):
                    msg = logger.insert_space(f"Share Limit: Max Seed Time = {str(timedelta(minutes=max_seeding_time))}", 4)
                    body.append(msg)
                elif max_ratio != torrent.max_ratio or max_seeding_time != torrent.max_seeding_time:
                    msg = logger.insert_space(
                        f"Share Limit: Max Ratio = {max_ratio}, Max Seed Time = {str(timedelta(minutes=max_seeding_time))}", 4
                    )
                    body.append(msg)
        # Update Torrents
        if not self.config.dry_run:
            if tags:
                torrent.add_tags(tags)
            torrent_upload_limit = -1 if round(torrent.up_limit / 1024) == 0 else round(torrent.up_limit / 1024)
            if limit_upload_speed is not None and limit_upload_speed != torrent_upload_limit:
                if limit_upload_speed == -1:
                    torrent.set_upload_limit(-1)
                else:
                    torrent.set_upload_limit(limit_upload_speed * 1024)
            if max_ratio is None:
                max_ratio = torrent.max_ratio
            if max_seeding_time is None:
                max_seeding_time = torrent.max_seeding_time
            if is_tag_in_torrent(self.min_seeding_time_tag, torrent.tags):
                return []
            if is_tag_in_torrent(self.min_num_seeds_tag, torrent.tags):
                return []
            if is_tag_in_torrent(self.last_active_tag, torrent.tags):
                return []
            torrent.set_share_limits(ratio_limit=max_ratio, seeding_time_limit=max_seeding_time, inactive_seeding_time_limit=-2)
        [logger.print_line(msg, self.config.loglevel) for msg in body if do_print]
        return body

    def has_reached_seed_limit(
        self,
        torrent,
        max_ratio,
        max_seeding_time,
        max_last_active,
        min_seeding_time,
        min_num_seeds,
        min_last_active,
        resume_torrent,
        tracker,
    ):
        """Check if torrent has reached seed limit"""
        body = ""
        torrent_tags = torrent.tags

        def _remove_min_seeding_time_tag():
            nonlocal torrent_tags
            if is_tag_in_torrent(self.min_seeding_time_tag, torrent_tags):
                if not self.config.dry_run:
                    torrent.remove_tags(tags=self.min_seeding_time_tag)

        def _has_reached_min_seeding_time_limit():
            nonlocal torrent_tags
            print_log = []
            if torrent.seeding_time >= min_seeding_time * 60:
                _remove_min_seeding_time_tag()
                return True
            else:
                if not is_tag_in_torrent(self.min_seeding_time_tag, torrent_tags):
                    print_log += logger.print_line(logger.insert_space(f"Torrent Name: {torrent.name}", 3), self.config.loglevel)
                    print_log += logger.print_line(logger.insert_space(f"Tracker: {tracker}", 8), self.config.loglevel)
                    print_log += logger.print_line(
                        logger.insert_space(
                            f"Min seed time not met: {str(timedelta(seconds=torrent.seeding_time))} <="
                            f" {str(timedelta(minutes=min_seeding_time))}. Removing Share Limits so qBittorrent can continue"
                            " seeding.",
                            8,
                        ),
                        self.config.loglevel,
                    )
                    print_log += logger.print_line(
                        logger.insert_space(f"Adding Tag: {self.min_seeding_time_tag}", 8), self.config.loglevel
                    )
                    if not self.config.dry_run:
                        torrent.add_tags(self.min_seeding_time_tag)
                        torrent_tags += f", {self.min_seeding_time_tag}"
                        torrent.set_share_limits(ratio_limit=-1, seeding_time_limit=-1, inactive_seeding_time_limit=-1)
                        torrent.set_upload_limit(-1)
                        if resume_torrent:
                            torrent.resume()
            return False

        def _is_less_than_min_num_seeds():
            nonlocal torrent_tags
            print_log = []
            if min_num_seeds == 0 or torrent.num_complete >= min_num_seeds:
                if is_tag_in_torrent(self.min_num_seeds_tag, torrent_tags):
                    if not self.config.dry_run:
                        torrent.remove_tags(tags=self.min_num_seeds_tag)
                return False
            else:
                if not is_tag_in_torrent(self.min_num_seeds_tag, torrent_tags):
                    print_log += logger.print_line(logger.insert_space(f"Torrent Name: {torrent.name}", 3), self.config.loglevel)
                    print_log += logger.print_line(logger.insert_space(f"Tracker: {tracker}", 8), self.config.loglevel)
                    print_log += logger.print_line(
                        logger.insert_space(
                            f"Min number of seeds not met: Total Seeds ({torrent.num_complete}) < "
                            f"min_num_seeds({min_num_seeds}). Removing Share Limits so qBittorrent can continue"
                            " seeding.",
                            8,
                        ),
                        self.config.loglevel,
                    )
                    print_log += logger.print_line(
                        logger.insert_space(f"Adding Tag: {self.min_num_seeds_tag}", 8), self.config.loglevel
                    )
                    if not self.config.dry_run:
                        torrent.add_tags(self.min_num_seeds_tag)
                        torrent_tags += f", {self.min_num_seeds_tag}"
                        torrent.set_share_limits(ratio_limit=-1, seeding_time_limit=-1, inactive_seeding_time_limit=-1)
                        torrent.set_upload_limit(-1)
                        if resume_torrent:
                            torrent.resume()
            return True

        def _has_reached_min_last_active_time_limit():
            nonlocal torrent_tags
            print_log = []
            now = int(time())
            inactive_time_minutes = round((now - torrent.last_activity) / 60)
            if inactive_time_minutes >= min_last_active:
                if is_tag_in_torrent(self.last_active_tag, torrent_tags):
                    if not self.config.dry_run:
                        torrent.remove_tags(tags=self.last_active_tag)
                return True
            else:
                if not is_tag_in_torrent(self.last_active_tag, torrent_tags):
                    print_log += logger.print_line(logger.insert_space(f"Torrent Name: {torrent.name}", 3), self.config.loglevel)
                    print_log += logger.print_line(logger.insert_space(f"Tracker: {tracker}", 8), self.config.loglevel)
                    print_log += logger.print_line(
                        logger.insert_space(
                            f"Min inactive time not met: {str(timedelta(minutes=inactive_time_minutes))} <="
                            f" {str(timedelta(minutes=min_last_active))}. Removing Share Limits so qBittorrent can continue"
                            " seeding.",
                            8,
                        ),
                        self.config.loglevel,
                    )
                    print_log += logger.print_line(
                        logger.insert_space(f"Adding Tag: {self.last_active_tag}", 8), self.config.loglevel
                    )
                    if not self.config.dry_run:
                        torrent.add_tags(self.last_active_tag)
                        torrent_tags += f", {self.last_active_tag}"
                        torrent.set_share_limits(ratio_limit=-1, seeding_time_limit=-1, inactive_seeding_time_limit=-1)
                        torrent.set_upload_limit(-1)
                        if resume_torrent:
                            torrent.resume()
            return False

        def _has_reached_seeding_time_limit():
            nonlocal body
            seeding_time_limit = None
            if max_seeding_time is None or max_seeding_time == -1:
                return False
            if max_seeding_time >= 0:
                seeding_time_limit = max_seeding_time
            elif max_seeding_time == -2 and self.qbt.global_max_seeding_time_enabled:
                seeding_time_limit = self.qbt.global_max_seeding_time
            else:
                _remove_min_seeding_time_tag()
                return False
            if seeding_time_limit is not None:
                if (torrent.seeding_time >= seeding_time_limit * 60) and _has_reached_min_seeding_time_limit():
                    body += logger.insert_space(
                        f"Seeding Time vs Max Seed Time: {str(timedelta(seconds=torrent.seeding_time))} >= "
                        f"{str(timedelta(minutes=seeding_time_limit))}",
                        8,
                    )
                    return True
            return False

        def _has_reached_max_last_active_time_limit():
            """Check if the torrent has been inactive longer than the max last active time"""
            nonlocal body
            now = int(time())
            inactive_time_minutes = round((now - torrent.last_activity) / 60)
            if max_last_active is not None and max_last_active != -1:
                if (inactive_time_minutes >= max_last_active) and _has_reached_min_last_active_time_limit():
                    body += logger.insert_space(
                        f"Inactive Time vs Max Last Active Time: {str(timedelta(minutes=inactive_time_minutes))} >= "
                        f"{str(timedelta(minutes=max_last_active))}",
                        8,
                    )
                    return True
            return False

        if min_num_seeds is not None:
            if _is_less_than_min_num_seeds():
                return body
        if min_last_active is not None:
            if not _has_reached_min_last_active_time_limit():
                return body
        if max_ratio is not None and max_ratio != -1:
            if max_ratio >= 0:
                if torrent.ratio >= max_ratio and _has_reached_min_seeding_time_limit():
                    body += logger.insert_space(f"Ratio vs Max Ratio: {torrent.ratio:.2f} >= {max_ratio:.2f}", 8)
                    return body
            elif max_ratio == -2 and self.qbt.global_max_ratio_enabled and _has_reached_min_seeding_time_limit():
                if torrent.ratio >= self.qbt.global_max_ratio:
                    body += logger.insert_space(
                        f"Ratio vs Global Max Ratio: {torrent.ratio:.2f} >= {self.qbt.global_max_ratio:.2f}", 8
                    )
                    return body
        if _has_reached_seeding_time_limit():
            return body
        if _has_reached_max_last_active_time_limit():
            return body
        return False

    def delete_share_limits_suffix_tag(self):
        """ "Delete Share Limits Suffix Tag from version 4.0.0"""
        tags = self.client.torrent_tags.tags
        old_share_limits_tag = self.share_limits_tag[1:] if self.share_limits_tag.startswith("~") else self.share_limits_tag
        for tag in tags:
            if tag.endswith(f".{old_share_limits_tag}"):
                self.client.torrent_tags.delete_tags(tag)
