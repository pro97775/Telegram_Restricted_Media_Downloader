# TRMD Frequently Asked Questions

This guide summarizes common errors and their fixes. Upgrade to the stated version or a newer release when a fix is listed.

## 1. The account is forcibly logged out on all devices

**Cause:** The bundled Pyrogram client is obsolete and triggers Telegram's forced logout behavior.

**Fix:** Upgrade to v1.1.9 or later, sign in to Telegram on a mobile device, and remove the application's `sessions` folder before signing in again.

## 2. `401 SESSION_REVOKED`

**Cause:** The login session is no longer valid, for example because all sessions were terminated from another device.

**Fix:** Upgrade to v1.1.9 or later, remove the `sessions` folder, and sign in again using the phone verification code.

## 3. `database is locked`

**Cause:** Another application instance is still running and is holding the database open.

**Fix:** Close all other TRMD instances and leave only the intended process running.

## 4. `msg_id is too low` / `msg_id is too high`, or the application stops responding after setup

**Cause:** The system clock is out of sync, so Telegram rejects message identifiers.

**Fix on Windows:** Press `Win+R`, enter `timedate.cpl`, open the Internet Time settings, synchronize with `time.windows.com`, and restart TRMD. The application added a diagnostic prompt for this error in v1.5.2.

## 5. `expected str, bytes or os.PathLike object, not NoneType`

**Causes:** Some video files have no title, or a media-save path containing Chinese characters triggers a Nuitka compatibility issue.

**Fix:** Upgrade to v1.2.8 or later and use an English-only path for media storage.

## 6. `FileNotFoundError`

**Cause:** An internal application bug can cause a download to fail.

**Fix:** Upgrade to v1.2.9 or later.

## 7. Repeated configuration-file prompts

**Cause:** A bug in configuration validation causes the same prompt to appear repeatedly.

**Fix:** Upgrade to v1.3.0 or later.

## 8. `The API key is required for new authorizations`

**Cause:** Usually a network timeout or proxy problem; it is not generally an application defect.

**Fix:** Restart TRMD and retry until the authorization screen appears. Check the network and proxy settings if the problem continues.

## 9. Multi-task downloads are unavailable

**Cause:** Older releases do not support concurrent download tasks.

**Fix:** Upgrade to v1.3.7 or later.

## 10. The progress bar wraps onto another line

**Cause:** This is a display issue caused by a long filename; the same media is not downloaded again.

**Fix:** Upgrade to v1.4.1 or later.

## 11. Links such as `https://t.me/xxx/xxx/111` cannot be downloaded

**Cause:** Older releases do not support links to messages in topic-enabled channels.

**Fix:** Upgrade to v1.4.8 or later.

## 12. Private links containing `/c/` cannot be downloaded

**Cause:** Private-link parsing was incorrect for regular channels in v1.4.6 and for topic-enabled channels in v1.4.7. The account may also not be a member of the private channel.

**Fix:** Upgrade to v1.4.8 or later and confirm that the signed-in account has joined the channel.

## 13. The bot cannot forward messages with `/forward`

**Version requirements:** Basic forwarding requires v1.5.1 or later; topic forwarding and `/listen_forward` require v1.6.3 or later. Forwarding from comment threads is not supported.

**Restricted content:** If Telegram prevents forwarding, the bot can provide download and upload buttons (v1.6.7 or later). From v1.6.7, download-then-upload is enabled by default. Keeping or deleting the local file after upload can be changed under **Help → Settings → Upload settings**. Changes take effect after re-registering or restarting the listener.

## 14. `KeyError: 0`, connection timeouts, or `rich.run:1504` during login

**Causes:** An incorrect proxy setting, a VPN that blocks the configured proxy port, or a local-network/VPN problem.

**Fix:** Check that the configured proxy is reachable and that the VPN allows its port. Starting with v1.8.5, TRMD can detect and fill in the system proxy when one is configured. On Windows, press `Win+R`, enter `inetcpl.cpl`, select **Connections → LAN settings**, and inspect the proxy address and port. Enter the proxy host in `config.yaml` as `hostname` and its port as `port`; use `http` or `socks5` for the scheme (not `socks4`). A password is usually unnecessary unless the proxy application requires one. Also check the local network and VPN. A diagnostic prompt for this error was added in v1.5.3.

## 15. Counts in the exported link table look incorrect

**Cause:** Link statistics include all supported media types, not only the types selected for the current download. Comment-link statistics could also report totals larger than the actual download count.

**Fix:** Comment-link statistics were corrected in v1.5.9. In v2.0.2, totals were adjusted so skipped or unsupported types are not counted as downloaded items. A completion rate below 100% can still be expected when the link contains media types that were not selected.

## 16. The bot accepts a channel link but reports an error

**Cause:** Link parsing was incorrect in releases before v1.6.8.

**Fix:** Upgrade to v1.6.8 or later.

## Good practices

1. Keep TRMD up to date, especially when an issue has a version-specific fix.
2. Use English-only paths to avoid path-encoding and packaging problems.
3. Use a stable proxy and verify that the VPN allows its connection.
4. Keep the system clock synchronized to avoid invalid message identifiers.

The symbols in the original FAQ marked an issue, its cause, the proposed fix, and important notes; these headings make those roles explicit in this English edition.
