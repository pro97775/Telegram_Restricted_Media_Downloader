const EMPTY_SUMMARY = {percent: 0, info: '0.00B / 0.00B', speed: '', remaining: ''};
var connectionStatus = '';  // Connection status text sent by the backend, appended after the overall progress extra.

var SECTIONS = {
    download: ['download'],
    upload: ['upload'],
    listener: ['listener'],
    notice: ['notice'],  // Notification page: shows download, upload, and forwarding notices; requires the bot.
    storage: ['storage']  // Storage page: shows download and upload history from the database; does not require the bot.
};
var PAGES = SECTIONS.download.concat(SECTIONS.upload, SECTIONS.listener, SECTIONS.notice, SECTIONS.storage);  // One page each for downloads, uploads, notices, and history; listener tabs switch internally.
var SUMMARY_IDS = {
    download: {fill: 'overallFill', percent: 'overallPercent', info: 'overallInfo', extra: 'overallExtra', status: 'overallStatus'},
    upload: {fill: 'uploadFill', percent: 'uploadPercent', info: 'uploadInfo', extra: 'uploadExtra', status: 'uploadStatus'}
};  // Separate overall progress panels for downloads and uploads to prevent them from overwriting each other.
var SECTION_KEY = 'trmd_section';
var LISTEN_KEY = 'trmd_listen';
var NOTICE_KEY = 'trmd_notice';  // Local storage key for the notification page tab.
var HAS_BOT = document.body.getAttribute('data-bot') === '1';  // Whether a bot is configured; controls upload/listener sidebar visibility (without a bot, only downloads are available).
var HAS_STORAGE = document.body.getAttribute('data-storage') === '1';  // Whether the history database is available; controls the history sidebar (history does not require a bot).
var COLLAPSE_KEY = 'trmd_collapsed';  // Local storage key for each group's collapsed state.
var ALL_KEY = 'trmd_all_collapsed';  // Local storage key for the download page's collapse-all toggle.
var UPLOAD_ALL_KEY = 'trmd_upload_all_collapsed';  // Local storage key for the upload page's collapse-all toggle.
var LINK_LAST_KEY = 'trmd_link_last';  // Local storage key for the last manual selection of the download page's link level.
var UPLOAD_LAST_KEY = 'trmd_upload_last';  // Local storage key for the last manual selection of the upload page's channel level.
var LISTEN_TABS = ['forward', 'download'];  // Listener page tabs: forwarding and downloads.
var NOTICE_TABS = ['download', 'upload', 'forward'];  // Notification page tabs: downloads, uploads, and forwarding.

var STATE_TEXT = {
    pending: 'Queued',
    downloading: 'Downloading',
    success: 'Completed',
    skip: 'Skipped',
    failure: 'Failed'
};
var STATE_CLASS = {
    pending: 'status-pending',
    downloading: 'status-running',
    success: 'status-done',
    skip: 'status-skip',
    failure: 'status-failed'
};
var STATE_ICON = {
    pending: '⏳',
    downloading: '📥',
    success: '✅',
    skip: '⏭',
    failure: '❌'
};

var HEAD_LABELS = ['Channel', 'Channel / Link', 'Channel / Link / Name'];
var SIZE_LABELS = ['Completed / Total', 'Completed / Total', 'Count / Size'];
var UPLOAD_HEAD_NAME = ['Channel', 'Channel / File Path'];
var UPLOAD_HEAD_SIZE = ['Completed / Total', 'Size'];
var UPLOAD_TEXT = {
    pending: 'Queued',
    uploading: 'Uploading',
    success: 'Completed',
    sent: 'Completed',
    failure: 'Failed'
};
var UPLOAD_CLASS = {
    pending: 'status-pending',
    uploading: 'status-running',
    success: 'status-done',
    sent: 'status-done',
    failure: 'status-failed'
};
var UPLOAD_ICON = {
    pending: '⏳',
    uploading: '📤',
    success: '✅',
    sent: '✅',
    failure: '❌'
};
var collapsed = {};
var allCollapsed = false;
var uploadAllCollapsed = false;
var lastLinkCollapsed = true;  // Last manual selection for the download page's link level; collapsed by default to preserve the original default.
var lastUploadCollapsed = false;  // Last manual selection for the upload page's channel level; expanded by default to preserve the original default.
var UNGROUPED_NAME = 'Ungrouped';
var NOTICE_EMPTY_TEXT = {
    download: 'No download notifications yet.',
    upload: 'No upload notifications yet.',
    forward: 'No forwarding notifications yet.'
};
var currentSection = 'download';
var currentListen = 'forward';
var currentNotice = 'download';  // Current notification page tab; corresponds to NOTICE_TABS.
var lastSnapshot = null;  // Cache the latest progress snapshot to prefill the current save directory in the settings dialog.
var lastDownloadActive = 0;
var lastUploadActive = 0;
var lastListenCount = 0;
var lastPaused = false;  // Global paused state, updated with progress snapshots and used to synchronize the top-bar status and button.
var lastUploadFinished = 0;  // Number of finished uploads (successes + failures), used to advance the background gradient.

function esc(text) {
    var div = document.createElement('div');
    div.textContent = text === undefined || text === null ? '' : text;
    return div.innerHTML;
}

function escAttr(text) {
    return esc(text).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function dash(text) {
    return text ? esc(text) : '—';
}

function progressCell(percent) {
    // --p is used to turn the horizontal bar into a ring on mobile (a complete angle value including %); desktop does not read it, so it has no effect there.
    return '<span class="cell-progress" style="--p:' + percent + '%">' +
        '<span class="track"><span class="fill" style="width:' + percent + '%"></span></span>' +
        '<span class="pct">' + percent + '%</span></span>';
}

var SIZE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];  // Match the decimal units used by the terminal.

function sizeText(bytes) {
    var value = Number(bytes) || 0;
    var index = 0;
    while (value >= 1000 && index < SIZE_UNITS.length - 1) {
        value = value / 1000;
        index++;
    }
    return value.toFixed(2) + SIZE_UNITS[index];
}

function secondsText(seconds) {
    var total = Math.floor(Number(seconds) || 0);
    if (total < 60) {
        return total + ' sec';
    }
    if (total < 3600) {
        return Math.floor(total / 60) + ' min ' + (total % 60) + ' sec';
    }
    return Math.floor(total / 3600) + ' hr ' + Math.floor(total % 3600 / 60) + ' min ' + (total % 60) + ' sec';
}

function groupStat(members, live) {
    var speed = 0;
    var left = 0;
    for (var i = 0; i < members.length; i++) {
        var member = members[i];
        var task = live[member.task_id] || member;  // Upload members carry their own progress fields; fall back to the member if no progress task is found.
        if (member.state === 'success' || member.state === 'skip' || member.state === 'sent') {
            continue;  // Completed, skipped, and sent members no longer count toward speed or remaining time.
        }
        if (task && task.speed_value) {
            speed += Number(task.speed_value) || 0;
        }
        left += Math.max((Number(member.size_byte) || 0) - (Number(task && task.completed) || 0), 0);
    }
    return {speed: speed, remaining: speed && left > 0 ? left / speed : null};
}

function groupStatCells(stat) {
    var speed = stat.speed ? sizeText(stat.speed) + '/s' : '—';
    var remain = stat.remaining === null ? '—' : secondsText(stat.remaining);
    return '<span class="cell-speed">' + speed + '</span>' +
        '<span class="cell-remain">' + remain + '</span>';
}

function taskRow(task) {
    var done = task.percent >= 100;
    // data-task-id enables in-place progress updates when the list structure is unchanged, avoiding a full rebuild every second.
    return '<div class="task-row" data-task-id="' + escAttr(task.id) + '">' +
        '<span class="cell-name"><span class="ficon">' + esc(task.type || '📄') + '</span>' +
        '<span class="fname" title="' + escAttr(task.filename) + '">' + esc(task.filename) + '</span></span>' +
        progressCell(task.percent) +
        '<span class="cell-size">' + dash(task.info) + '</span>' +
        '<span class="cell-speed">' + dash(task.speed) + '</span>' +
        '<span class="cell-remain">' + dash(task.remaining) + '</span>' +
        '<span class="cell-status ' + (done ? 'status-done' : 'status-running') + '">' +
        (done ? 'Completed' : 'Downloading') + '</span>' +
        '</div>';
}

function memberRow(item) {
    var state = item.state || 'pending';
    var text = STATE_TEXT[state] || 'Queued';
    var cls = STATE_CLASS[state] || 'status-pending';
    var pending = state === 'pending';
    var progress;
    if (state === 'success') {
        progress = progressCell(100);
    } else if (item.note) {  // Unsupported or ignored types have no file type; show the specific reason in the progress bar to distinguish them from ordinary skips.
        progress = '<span class="cell-progress"><span class="pct note" title="' + escAttr(item.note) + '">' +
            esc(item.note) + '</span></span>';
    } else {
        progress = '<span class="cell-progress"><span class="pct' + (pending ? ' pending' : '') + '">' + text + '</span></span>';
    }
    return '<div class="task-row member-row">' +
        '<span class="cell-name"><span class="ficon">' + (STATE_ICON[state] || '⏳') + '</span>' +
        '<span class="fname" title="' + escAttr(item.name) + '">' + esc(item.name) + '</span>' +
        (item.date ? '<span class="gcount">' + esc(item.date) + '</span>' : '') +
        '</span>' +
        progress +
        '<span class="cell-size">' + dash(item.size) + '</span>' +
        '<span class="cell-speed">—</span>' +
        '<span class="cell-remain">—</span>' +
        '<span class="cell-status ' + cls + '">' + text + '</span>' +
        '</div>';
}

function linkStatusCell(link) {
    var remaining = link.remaining || 0;
    var failed = link.failed || 0;
    if (remaining) {
        return '<span class="cell-status status-pending">' + remaining + ' remaining</span>';
    }
    if (failed) {
        return '<span class="cell-status status-failed">' + failed + ' failed</span>';
    }
    return '<span class="cell-status status-done">Completed</span>';
}

function getChannelGroups(links) {
    var groups = [];  // Group download links by channel, preserving the order in which channels first appear.
    var index = {};
    var i;
    for (i = 0; i < links.length; i++) {
        var channel = links[i].channel || UNGROUPED_NAME;
        if (index[channel] === undefined) {
            index[channel] = groups.length;
            groups.push({channel: channel, name: '', links: []});
        }
        var group = groups[index[channel]];
        var name = links[i].channel_name || channel;
        if (name.length > group.name.length) {
            group.name = name;  // Use the most informative name for a channel; "Title (ID)" is longer than a bare ID.
        }
        group.links.push(links[i]);
    }
    for (i = 0; i < groups.length; i++) {
        var channelGroup = groups[i];
        channelGroup.count = channelGroup.links.length;
        channelGroup.complete = 0;
        channelGroup.member = 0;
        channelGroup.remaining = 0;
        channelGroup.failed = 0;
        channelGroup.members = [];  // Collect members from all links in the channel to calculate channel-level speed and remaining time.
        for (var j = 0; j < channelGroup.links.length; j++) {
            channelGroup.complete += channelGroup.links[j].complete || 0;
            channelGroup.member += channelGroup.links[j].member || 0;
            channelGroup.remaining += channelGroup.links[j].remaining || 0;
            channelGroup.failed += channelGroup.links[j].failed || 0;
            channelGroup.members = channelGroup.members.concat(channelGroup.links[j].queue || []);
        }
        var base = channelGroup.member - channelGroup.failed;  // Exclude permanently failed members from the progress denominator so progress can reach 100%.
        channelGroup.percent = base ?
            Math.round(channelGroup.complete / base * 1000) / 10 : 0;
    }
    return groups;
}

function channelBlock(group, live) {
    var key = 'channel:' + group.channel;
    var filtering = Boolean(statFilter.download);
    // Force expansion while filtering so results are not hidden by the collapsed state.
    var isCollapsed = filtering ? false : (collapsed[key] === undefined ? allCollapsed : collapsed[key]);
    var stat = groupStat(group.members || [], live);
    var html = '<div class="group' + (isCollapsed ? '' : ' open') + '" data-channel="' + escAttr(key) + '" data-level="1">' +
        '<div class="group-head" data-channel="' + escAttr(key) + '">' +
        '<span class="cell-name"><span class="arrow"></span>' +
        '<span class="ficon">📺</span>' +
        '<span class="gname" title="' + escAttr(group.name || group.channel) + '">' +
        esc(group.name || group.channel) + '</span>' +
        '<span class="gcount">' + group.count + ' links</span></span>' +
        progressCell(group.percent) +
        '<span class="cell-size">' + group.complete + '/' + group.member + '</span>' +
        groupStatCells(stat) +
        linkStatusCell(group) +
        '</div>' +
        '<div class="group-body"' + (isCollapsed ? ' style="display:none"' : '') + '>';
    var body = '';
    for (var i = 0; i < group.links.length; i++) {
        body += linkBlock(group.links[i], live);
    }
    if (filtering && !body) {
        return '';  // Hide the entire group when filtering leaves no matching content in the channel.
    }
    return html + body + '</div></div>';
}

function linkBlock(link, live) {
    var key = 'link:' + link.link;
    var filtering = Boolean(statFilter.download);
    var all = link.queue || [];
    var members = all;
    if (filtering) {
        members = all.filter(matchDownloadState);
        if (members.length === 0) {
            return '';  // Hide the link when filtering leaves no matching members.
        }
    } else {
        // Without a filter, sort cards by status: in progress > queued > completed/skipped > failed, keeping active tasks at the top.
        members = members.slice().sort(function (a, b) {
            return stateRank(a.state) - stateRank(b.state);
        });
    }
    // Force expansion while filtering; otherwise results may be hidden by the collapsed state.
    var isCollapsed = filtering ? false : (collapsed[key] === undefined ? lastLinkCollapsed : collapsed[key]);
    var stat = groupStat(all, live);
    var html = '<div class="group' + (isCollapsed ? '' : ' open') + '" data-channel="' + escAttr(key) + '" data-level="2">' +
        '<div class="group-head" data-channel="' + escAttr(key) + '">' +
        '<span class="cell-name"><span class="arrow"></span>' +
        '<span class="ficon">🔗</span>' +
        '<span class="fname" title="' + escAttr(link.link) + '">' + esc(link.link) + '</span>' +
        '<span class="gcount">' + (link.queue_total || 0) + ' remaining / ' + (link.total || 0) + ' total</span></span>' +
        progressCell(link.percent) +
        '<span class="cell-size">' + link.complete + '/' + link.member + '</span>' +
        groupStatCells(stat) +
        linkStatusCell(link) +
        '</div>' +
        '<div class="group-body"' + (isCollapsed ? ' style="display:none"' : '') + '>';
    for (var i = 0; i < members.length; i++) {
        var member = members[i];
        var task = member.state === 'downloading' ? live[member.task_id] : null;
        html += task ? taskRow(task) : memberRow(member);  // Downloading members reuse the task row with its progress bar.
    }
    if (members.length === 0) {
        html += '<div class="more">No messages for this link.</div>';
    }
    return html + '</div></div>';
}

function groupVisible(node) {
    for (var parent = node.parentNode; parent; parent = parent.parentNode) {
        if (parent.style && parent.style.display === 'none') {
            return false;  // The group is hidden if any ancestor level is collapsed.
        }
    }
    return true;
}

function syncHeadLabel() {
    var level = 1;
    var nodes = document.querySelectorAll('#download .group.open');
    for (var i = 0; i < nodes.length; i++) {
        var depth = nodes[i].getAttribute('data-level') === '2' ? 3 : 2;
        if (depth > level && groupVisible(nodes[i])) {
            level = depth;  // Use the deepest currently visible level.
        }
    }
    document.getElementById('headName').querySelector('.htext').textContent = HEAD_LABELS[level - 1];
    document.getElementById('headSize').querySelector('.htext').textContent = SIZE_LABELS[level - 1];  // Group rows show counts; only member rows show bytes.
}

function bindGroups() {
    // Bind group headers only on the download and upload pages; history page headers are for categorization only and are not collapsible.
    var nodes = document.querySelectorAll('#download .group-head, #upload .group-head');
    for (var i = 0; i < nodes.length; i++) {
        nodes[i].onclick = function () {
            var group = this.parentNode;
            var key = this.getAttribute('data-channel');
            var body = group.querySelector('.group-body');
            var hide = body.style.display !== 'none';  // If currently expanded, collapse it on click.
            body.style.display = hide ? 'none' : '';
            group.className = hide ? 'group' : 'group open';
            collapsed[key] = hide;
            saveState(COLLAPSE_KEY, JSON.stringify(collapsed));  // Save this collapsed state and restore it after a refresh.
            if (group.getAttribute('data-level') === '2') {
                lastLinkCollapsed = hide;  // Manual selection for the download page's link level.
                saveState(LINK_LAST_KEY, hide ? '1' : '0');
            } else if (group.closest('#upload')) {
                lastUploadCollapsed = hide;  // Manual selection for the upload page's channel level.
                saveState(UPLOAD_LAST_KEY, hide ? '1' : '0');
            }
            syncHeadLabel();
            syncUploadHeads();
        };
    }
}

function syncToggleAll() {
    document.getElementById('toggleAll').textContent = allCollapsed ? 'Expand All' : 'Collapse All';
}

function syncToggleUpload() {
    document.getElementById('toggleUpload').textContent = uploadAllCollapsed ? 'Expand All' : 'Collapse All';
}

function setAllGroups(selector, hide) {
    var nodes = document.querySelectorAll(selector + ' .group');
    for (var i = 0; i < nodes.length; i++) {
        var key = nodes[i].getAttribute('data-channel');
        var body = nodes[i].querySelector('.group-body');
        body.style.display = hide ? 'none' : '';
        nodes[i].className = hide ? 'group' : 'group open';
        collapsed[key] = hide;
    }
    saveState(COLLAPSE_KEY, JSON.stringify(collapsed));  // Persist the batch collapse operation as well so it remains after refresh.
    if (selector === '#download') {
        lastLinkCollapsed = hide;  // Treat the batch operation as a link-level selection as well.
        saveState(LINK_LAST_KEY, hide ? '1' : '0');
    } else {
        lastUploadCollapsed = hide;  // Treat the batch operation as a channel-level selection as well.
        saveState(UPLOAD_LAST_KEY, hide ? '1' : '0');
    }
}

function toggleAll() {
    allCollapsed = !allCollapsed;
    saveState(ALL_KEY, allCollapsed ? '1' : '0');
    setAllGroups('#download', allCollapsed);
    syncToggleAll();
    syncHeadLabel();
}

function toggleUploadAll() {
    uploadAllCollapsed = !uploadAllCollapsed;
    saveState(UPLOAD_ALL_KEY, uploadAllCollapsed ? '1' : '0');
    setAllGroups('#upload', uploadAllCollapsed);
    syncToggleUpload();
    syncUploadHeads();
}

function saveState(key, value) {
    try {
        localStorage.setItem(key, value);
    } catch (e) {
        // A failed write in private browsing mode can be ignored.
    }
}

function applySection() {
    var items = document.querySelectorAll('.side-item');
    for (var i = 0; i < items.length; i++) {
        var active = items[i].getAttribute('data-section') === currentSection;
        items[i].className = active ? 'side-item active' : 'side-item';
    }
    var dlWasHidden = document.getElementById('downloadSummary').hidden;
    var storageWasHidden = document.getElementById('page-storage').hidden;
    var noticeWasHidden = document.getElementById('page-notice').hidden;
    document.getElementById('downloadSummary').hidden = currentSection !== 'download';
    document.getElementById('uploadSummary').hidden = currentSection !== 'upload';  // Each section has its own overall progress.
    for (i = 0; i < PAGES.length; i++) {
        document.getElementById('page-' + PAGES[i]).hidden = PAGES[i] !== currentSection;
    }
    renderStatus();
    // When the overall download progress card becomes visible, force one progress-bar redraw with the latest data,
    // so it is not rendered while hidden on first load or when returning to the download page, which could skip or hide the bar.
    if (currentSection === 'download' && dlWasHidden) {
        refresh(true);
    }
    // Fetch immediately when the notification page becomes visible: notices are sent by section, and without a forced refresh we would wait for a polling cycle.
    if (currentSection === 'notice' && noticeWasHidden) {
        refresh(true);
    }
    if (currentSection === 'storage' && storageWasHidden) {
        refreshStorage();  // Fetch immediately when the history page becomes visible to avoid showing stale data from the previous visit.
    }
}

function switchSection(name) {
    if (!SECTIONS[name]) {
        name = 'download';
    }
    if (!HAS_BOT && name !== 'download' && name !== 'storage') {  // Without a configured bot, allow only the download and history pages to prevent landing on unavailable upload/listener pages.
        name = 'download';
    }
    if (!HAS_STORAGE && name === 'storage') {  // Fall back to the download page when the history database is unavailable.
        name = 'download';
    }
    currentSection = name;
    applySection();
    saveState(SECTION_KEY, currentSection);
}

function applySectionVisibility() {
    // Uploads, listeners, and notifications require a bot; hide these three entries if none is configured so clicks do not appear to do nothing.
    if (!HAS_BOT) {
        var botItems = document.querySelectorAll('.side-item[data-section="upload"], .side-item[data-section="listener"], .side-item[data-section="notice"]');
        for (var i = 0; i < botItems.length; i++) {
            botItems[i].hidden = true;
        }
    }
    // Show the history entry only when the database is available; otherwise hide it to avoid an empty page.
    var storageItem = document.querySelector('.side-item[data-section="storage"]');
    if (storageItem) {
        storageItem.hidden = !HAS_STORAGE;
    }
    // When neither a bot nor history is available, downloads are the only feature; hide the sidebar and use a single-column layout.
    if (HAS_BOT || HAS_STORAGE) {
        return;
    }
    var sidebar = document.getElementById('sidebar');
    if (sidebar) {
        sidebar.hidden = true;
    }
    var layout = document.querySelector('.layout');
    if (layout && !layout.classList.contains('layout-single')) {
        layout.classList.add('layout-single');
    }
}

function applyListenTab() {
    var tabs = document.querySelectorAll('#listenTabs .tab');
    for (var i = 0; i < tabs.length; i++) {
        var active = tabs[i].getAttribute('data-listen') === currentListen;
        tabs[i].className = active ? 'tab active' : 'tab';
    }
    document.getElementById('listenForwardBox').hidden = currentListen !== 'forward';
    document.getElementById('listenDownloadBox').hidden = currentListen !== 'download';
}

function switchListen(name) {
    if (LISTEN_TABS.indexOf(name) === -1) {
        name = LISTEN_TABS[0];
    }
    currentListen = name;
    applyListenTab();
    saveState(LISTEN_KEY, currentListen);
}

function extraText(item) {
    var extra = '';
    if (item.speed) {
        extra += item.speed;
    }
    if (item.remaining) {
        extra += (extra ? ' • ' : '') + 'Remaining: ' + item.remaining;
    }
    return extra;
}

function renderOverall(summary, taskCount, ids) {
    var data = summary || EMPTY_SUMMARY;
    document.getElementById(ids.fill).style.width = data.percent + '%';
    document.getElementById(ids.percent).textContent = data.percent + '%';
    document.getElementById(ids.info).textContent = data.info;
    document.getElementById(ids.extra).textContent =
        extraText(data) ? extraText(data) : (taskCount ? 'Measuring speed…' : 'Speed unavailable');
    document.getElementById(ids.status).textContent = connectionStatus;
}

/* Statistic card filters: click to show entries with the selected status; click again to clear the filter. */
var statFilter = {download: '', upload: ''};

// Empty-state messages when filtering yields no matches, consistent with the statistic card filter criteria.
var DOWNLOAD_EMPTY_TEXT = {
    success: 'No completed downloads.',
    failure: 'No failed downloads.',
    skip: 'No skipped downloads.',
    active: 'No downloads in progress.',
    queue: 'No queued downloads.'
};
var UPLOAD_EMPTY_TEXT = {
    success: 'No completed uploads.',
    failure: 'No failed uploads.',
    uploading: 'No uploads in progress.',
    pending: 'No queued uploads.'
};

function statCell(label, value, cls, filter, scope) {
    if (!filter || !scope) {
        return '<div><span>' + label + '</span><b' + (cls ? ' class="' + cls + '"' : '') + '>' +
            value + '</b></div>';
    }
    var active = statFilter[scope] === filter;
    return '<div class="' + (active ? 'active ' : '') + '"' +
        ' data-filter="' + filter + '" data-scope="' + scope + '"' +
        ' title="' + (active ? 'Click to clear filter' : 'Show only ' + label) + '">' +
        '<span>' + label + '</span><b' + (cls ? ' class="' + cls + '"' : '') + '>' +
        value + '</b></div>';
}

// Check whether a download member matches the current filter.
function matchDownloadState(member) {
    var state = member.state || 'pending';
    var filter = statFilter.download;
    if (filter === 'success') {
        return state === 'success' || state === 'sent';
    }
    if (filter === 'failure') {
        return state === 'failure';
    }
    if (filter === 'skip') {
        return state === 'skip';
    }
    if (filter === 'active') {
        return state === 'downloading';
    }
    if (filter === 'queue') {
        return state === 'pending';
    }
    return true;
}

/* Count members "queued": include only queued items, not those currently downloading.
   Backend data.queue is the total number of unfinished items (including downloads in progress); displaying it directly would double-count active items. */
function countQueueMembers(links) {
    var total = 0;
    for (var i = 0; i < (links || []).length; i++) {
        var members = links[i].queue || [];
        for (var j = 0; j < members.length; j++) {
            var state = members[j].state || 'pending';
            if (state === 'pending') {
                total += 1;
            }
        }
    }
    return total;
}

// Check whether an uploaded file matches the specified filter, using the same categories as uploadCount.
function matchUploadState(file, filter) {
    var state = file.state || 'pending';
    if (filter === 'success') {
        return uploadDone(file);
    }
    if (filter === 'failure') {
        return state === 'failure';
    }
    if (filter === 'uploading') {
        return !uploadDone(file) && state === 'uploading';
    }
    if (filter === 'pending') {
        return !uploadDone(file) && state !== 'failure' && state !== 'uploading';
    }
    return true;  // Counts such as total files are not filtered.
}


function bindStatFilter() {
    document.addEventListener('click', function (event) {
        var cell = event.target && event.target.closest ? event.target.closest('[data-filter]') : null;
        if (!cell) {
            return;
        }
        var scope = cell.getAttribute('data-scope') || 'download';
        var value = cell.getAttribute('data-filter') || '';
        statFilter[scope] = statFilter[scope] === value ? '' : value;  // Clicking again clears the filter.
        // Filter state belongs to the UI, not the snapshot data, so clear the fingerprints to force a redraw;
        // otherwise the unchanged data check would skip rendering and the click would appear to do nothing.
        lastRenderKey = '';
        lastStructKey = null;
        lastUploadStructKey = null;
        refresh();  // Redraw immediately with the new filter instead of waiting for the next poll.
    });
}

function renderStat(id, cells) {
    document.getElementById(id).innerHTML = cells.join('');
}

function renderStatus() {
    // Show activity for downloads, uploads, and listeners together on the left side of the top bar, regardless of the current section.
    var parts = [];
    if (lastPaused) {
        parts.push('Paused');
    }
    if (lastDownloadActive) {
        parts.push('Downloads ' + lastDownloadActive);
    }
    if (lastUploadActive) {
        parts.push('Uploads ' + lastUploadActive);
    }
    if (lastListenCount) {
        parts.push('Listeners ' + lastListenCount);
    }
    var active = parts.length > 0;
    document.getElementById('dot').className = active ? 'dot active' : 'dot';
    document.getElementById('statusText').textContent = active ? parts.join(' · ') : 'Idle · Waiting for tasks';
}

function renderList(data) {
    var live = {};  // Progress-bar task ID -> task, allowing members being downloaded to reuse live progress.
    var i;
    for (i = 0; i < (data.tasks || []).length; i++) {
        live[data.tasks[i].id] = data.tasks[i];
    }
    var html = '';
    var groups = getChannelGroups(data.links || []);  // Channel > link > download information; both levels can be collapsed.
    for (i = 0; i < groups.length; i++) {
        html += channelBlock(groups[i], live);
    }
    /* Determine the empty state by whether the link still has members (including completed ones), not by whether any tasks are downloading.
       Otherwise, once all downloads finish, data.tasks is empty and the empty state hides all completed members,
       which would remain hidden until a new task is created. */
    // When filtering, if there are no matches, show the specific filter condition instead of the generic "No download tasks yet.".
    var emptyText = 'No download tasks yet.';
    if (statFilter.download) {
        emptyText = DOWNLOAD_EMPTY_TEXT[statFilter.download] || emptyText;
    }
    document.getElementById('download').innerHTML = html ? html : '<div class="empty">' + emptyText + '</div>';
    syncToggleAll();
    bindGroups();  // Bind collapse events after rendering the page.
    syncHeadLabel();
}

function listenRow(kind, source, target) {
    var link = target ? source + ' ' + target : source;  // Keep consistent with the keys in the backend listener dictionary.
    var html = '<div class="task-row">' +
        '<span class="cell-name"><span class="ficon">🕵️</span>' +
        '<span class="fname" title="' + escAttr(source) + '">' + esc(source) + '</span></span>';
    if (target) {
        html += '<span class="cell-name"><span class="ficon">➡️</span>' +
            '<span class="fname" title="' + escAttr(target) + '">' + esc(target) + '</span></span>';
    }
    html += '<span class="cell-action"><button class="btn-del" type="button" title="Remove listener"' +
        ' data-kind="' + kind + '" data-link="' + escAttr(link) + '">✖</button></span>';
    return html + '</div>';
}

function renderListeners(listeners) {
    var data = listeners || {};
    var forward = data.forward || [];
    var download = data.download || [];
    var html = '';
    var i;
    for (i = 0; i < forward.length; i++) {
        html += listenRow('forward', forward[i].source, forward[i].target);
    }
    document.getElementById('listenForward').innerHTML = html ? html : '<div class="empty">No forwarding listeners yet.</div>';
    html = '';
    for (i = 0; i < download.length; i++) {
        html += listenRow('download', download[i]);
    }
    document.getElementById('listenDownload').innerHTML = html ? html : '<div class="empty">No download listeners yet.</div>';
    return forward.length + download.length;
}

/* Notification page: show download, upload, and forwarding notices registered by the notification center.
   Notices are placed in tabs by type; the content column shows details, the creator column shows who created the task, and the time column shows when it was registered. */
function noticeRow(notice) {
    // Notice content may contain line breaks (such as a forwarding failure reason); convert them to <br> to preserve the original layout.
    return '<div class="task-row notice-row">' +
        '<span class="cell-name notice-text">' + esc(notice.text).replace(/\n/g, '<br>') + '</span>' +
        '<span class="cell-name"><span class="fname" title="' + escAttr(notice.owner_name) + '">' +
        dash(notice.owner_name) + '</span></span>' +
        '<span class="cell-remain">' + dash(notice.time) + '</span>' +
        '</div>';
}

/* Notice structure fingerprint: index + registration time + content. Including the index distinguishes notices with identical content and timestamps,
   and ensures the fingerprint changes when a new notice is inserted or an old one is trimmed, preventing missed renders. */
function noticeStructKey(notices) {
    var parts = [];
    for (var i = 0; i < notices.length; i++) {
        parts.push(i + '|' + notices[i].time + '|' + notices[i].text);
    }
    return parts.join(';');
}

var lastNoticeKey = null;  // Fingerprint of the last rendered notices; skip rebuilding when unchanged. (Initially null rather than '', otherwise an empty notice list would have an empty fingerprint and be mistaken as "unchanged," so the empty state would never render.)

function renderNotices(notices) {
    var data = notices || {};
    var items = data[currentNotice] || [];
    var key = currentNotice + '#' + noticeStructKey(items);
    if (key === lastNoticeKey) {
        return;  // No notices changed in the current tab; keep the existing DOM.
    }
    lastNoticeKey = key;
    var html = '';
    var i;
    for (i = 0; i < items.length; i++) {
        html += noticeRow(items[i]);
    }
    document.getElementById('notice').innerHTML = html ?
        html : '<div class="empty">' + (NOTICE_EMPTY_TEXT[currentNotice] || NOTICE_EMPTY_TEXT.download) + '</div>';
}

function applyNoticeTab() {
    var tabs = document.querySelectorAll('#noticeTabs .tab');
    for (var i = 0; i < tabs.length; i++) {
        var active = tabs[i].getAttribute('data-notice') === currentNotice;
        tabs[i].className = active ? 'tab active' : 'tab';
    }
    lastNoticeKey = null;  // Force a redraw after switching tabs so the fingerprint does not mark it as "unchanged" and skip it.
    // If the cached snapshot has no notices field, it was fetched for another section (we just switched to notifications and the forced refresh has not returned yet).
    // Skip rendering for now and keep the old content to avoid a brief empty state before the refresh arrives; render will update it when the response is received.
    if (lastSnapshot && lastSnapshot.notices) {
        renderNotices(lastSnapshot.notices);
    }
}

function switchNotice(name) {
    if (NOTICE_TABS.indexOf(name) === -1) {
        name = NOTICE_TABS[0];
    }
    currentNotice = name;
    applyNoticeTab();
    saveState(NOTICE_KEY, currentNotice);
}

function bindNoticeTabs() {
    var tabs = document.querySelectorAll('#noticeTabs .tab');
    for (var i = 0; i < tabs.length; i++) {
        tabs[i].onclick = function () {
            switchNotice(this.getAttribute('data-notice'));
        };
    }
}

/* History page: show download and upload history from the database.
   The backend checks in real time when reading whether files still exist and discards missing entries, so the frontend only displays the results.
   Flat table: channel and link are columns, sorted by channel and link; entries in each group retain the API's returned order from newest to oldest. */
var STORAGE_TABS = ['download', 'upload'];  // History page tabs: downloads and uploads.
var STORAGE_KEY = 'trmd_storage';  // Local storage key for the history page tab.
var STORAGE_POLL_INTERVAL_MS = 3000;  // History page polling interval; less frequent than the progress page to avoid querying the database too often.

var STORAGE_EMPTY_TEXT = {
    download: 'No download records yet.',
    upload: 'No upload records yet.'
};
var currentStorage = 'download';
var STORAGE_TEXT = {
    success: 'Completed',
    skip: 'Skipped',
    failure: 'Failed'
};
var STORAGE_CLASS = {
    success: 'status-done',
    skip: 'status-skip',
    failure: 'status-failed'
};
var STORAGE_ICON = {
    download: '📥',
    upload: '📤'
};
var STORAGE_UPLOAD_LINK = 'Local upload';
var STORAGE_HEADERS = {
    download: ['Channel / Message', 'File', 'Link', 'Size', 'Message ID', 'Type', 'Status', 'Time'],
    upload:   ['Channel', 'File Path', 'Size', 'Type', 'Status', 'Time']
};
var STORAGE_COLS = {
    download: '150px minmax(200px, 1fr) 200px 100px 90px 90px 90px 150px',
    upload:   '150px minmax(200px, 1fr) 100px 90px 90px 150px'
};

/* Filter column definitions: correspond to STORAGE_HEADERS in order; kind determines the filter type (text/number/date).
   Each column key maps to storageFilterValue's lookup logic, and the value list comes from the same source as the cell display, so filtering matches what the user sees. */
var STORAGE_FILTER_COLS = {
    download: [
        {key: 'chat', kind: 'text'},
        {key: 'file', kind: 'text'},
        {key: 'link', kind: 'text'},
        {key: 'size', kind: 'number', unit: 'MB', arg: 'Enter size (MB)'},
        {key: 'mid', kind: 'number'},
        {key: 'type', kind: 'text'},
        {key: 'state', kind: 'text'},
        {key: 'time', kind: 'date'}
    ],
    upload: [
        {key: 'chat', kind: 'text'},
        {key: 'path', kind: 'text'},
        {key: 'size', kind: 'number', unit: 'MB', arg: 'Enter size (MB)'},
        {key: 'type', kind: 'text'},
        {key: 'state', kind: 'text'},
        {key: 'time', kind: 'date'}
    ]
};
var STORAGE_FILTER_OPS = {  // Custom-condition operators, grouped by column type.
    text: [
        {op: 'contains', label: 'Contains'},
        {op: 'equals', label: 'Equals'},
        {op: 'notEquals', label: 'Does not equal'},
        {op: 'begins', label: 'Starts with'},
        {op: 'ends', label: 'Ends with'}
    ],
    number: [
        {op: 'greater', label: 'Greater than'},
        {op: 'less', label: 'Less than'},
        {op: 'equals', label: 'Equals'},
        {op: 'between', label: 'Between'}
    ],
    date: [
        {op: 'equals', label: 'On'},
        {op: 'after', label: 'After'},
        {op: 'before', label: 'Before'},
        {op: 'between', label: 'Between'}
    ]
};
var STORAGE_FILTER_CUSTOM_LABEL = {  // Entry text for switching to custom conditions in the panel.
    text: 'Filter text',
    number: 'Filter numbers',
    date: 'Filter dates'
};
var STORAGE_FILTER_ARG_LABEL = {  // Placeholders for custom-condition inputs.
    text: 'Enter a keyword',
    number: 'Enter a value',
    date: 'Enter a date (YYYY-MM-DD)'
};
var STORAGE_FILTER_EMPTY = {  // Empty-state messages when filtering yields no results.
    download: 'No download records match the current filters.',
    upload: 'No upload records match the current filters.'
};
var STORAGE_FILTER_KEY = 'trmd_storage_filters';  // Local storage key for filters, which remain active after refresh.
var FILTER_MB = 1024 * 1024;  // Custom size filters are entered in MB and converted to bytes when saved for comparison with size_byte.
/* Header filter-button icons: dropdown arrow when inactive, funnel when filtering; CSS toggles their visibility. */
var STORAGE_FILTER_ICONS =
    '<svg class="hfilter-arrow" width="10" height="6" viewBox="0 0 10 6" aria-hidden="true">' +
    '<path d="M1 1l4 4 4-4" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>' +
    '<svg class="hfilter-funnel" width="11" height="10" viewBox="0 0 12 12" aria-hidden="true">' +
    '<path d="M1.5 2h9L7.6 6.6V10L4.4 8.4V6.6L1.5 2z" stroke="currentColor" stroke-width="1.3" fill="none" stroke-linejoin="round"/></svg>';
var storageFilters = {download: {}, upload: {}};  // Each tab stores its own filters: column key -> {mode:'values',values} or {mode:'custom',op,value,value2}.
var storageFilterPop = null;  // Currently open filter panel; only one can be open at a time.
var storageFilterPanel = null;  // Temporary selections while the panel is open; write back to storageFilters on Apply and discard on Cancel.
var storageFilterCol = '';  // Column key currently being filtered in the panel.
var storageFilterInnerDown = false;  // Whether the pointer started inside the panel, preventing text selection dragged outside an input from being mistaken for an outside click.
var storageFilterEntries = null;  // Cache the current column values when opening the panel; shared by matched and fillStorageFilterValues to avoid repeated traversal.

/* Rebuild the header, column widths, and drag handles for the current storage tab (download/upload).
   Downloads retain the original 8 columns (including link and message ID, grouped by message); uploads have 6 columns (no link/message ID, grouped by channel). */
function applyStorageLayout() {
    var list = document.querySelector('.list-storage');
    if (!list) {
        return;
    }
    var head = list.querySelector('.list-head');
    if (!head) {
        return;
    }
    var headers = STORAGE_HEADERS[currentStorage] || STORAGE_HEADERS.download;
    var cols = STORAGE_FILTER_COLS[currentStorage] || STORAGE_FILTER_COLS.download;
    var html = '';
    for (var i = 0; i < headers.length; i++) {
        var active = cols[i] && storageFilters[currentStorage][cols[i].key] ? ' active' : '';
        html += '<span><span class="htext">' + esc(headers[i]) + '</span>' +
            '<button type="button" class="hfilter' + active + '" data-filter="' + cols[i].key + '" title="Filter">' +
            STORAGE_FILTER_ICONS + '</button></span>';
    }
    head.innerHTML = html;
    list.style.setProperty('--cols', STORAGE_COLS[currentStorage] || STORAGE_COLS.download);
    initCols();  // Rebuild drag handles for the new column count and widths; old handles are removed with head.innerHTML and will not be duplicated.
}

function applyStorageTab() {
    var tabs = document.querySelectorAll('#storageTabs .tab');
    for (var i = 0; i < tabs.length; i++) {
        var active = tabs[i].getAttribute('data-storage') === currentStorage;
        tabs[i].className = active ? 'tab active' : 'tab';
    }
    applyStorageLayout();  // Sync the header, column widths, and drag handles with the current tab layout.
}

function switchStorage(name) {
    if (STORAGE_TABS.indexOf(name) === -1) {
        name = 'download';
    }
    closeStorageFilterPop();  // Close the filter panel before rebuilding the header so it does not become misaligned with the new header.
    currentStorage = name;
    applyStorageTab();
    saveState(STORAGE_KEY, currentStorage);
    storagePage.index = 0;  // Return to the first page when switching types so the page index is valid for the new type.
    refreshStorage();
}

function bindStorageTabs() {
    var tabs = document.querySelectorAll('#storageTabs .tab');
    for (var i = 0; i < tabs.length; i++) {
        tabs[i].onclick = function () {
            switchStorage(this.getAttribute('data-storage'));
        };
    }
    var btn = document.getElementById('toggleStorage');
    if (btn) {
        btn.onclick = refreshStorage;  // Manual refresh button.
    }
}

/* Grouped sorting: first by channel, then by link.
   Within the same link (message or comment), downloads sort by message ID ascending; for comments, message_id is the comment ID,
   so the link column appears in ascending order. Uploads sort by record ID descending. Array.prototype.sort is stable in modern browsers. */
function sortStorage(storages) {
    return storages.slice().sort(function (a, b) {
        var chatA = a.chat || '';
        var chatB = b.chat || '';
        if (chatA !== chatB) {
            return chatA < chatB ? -1 : 1;
        }
        if (currentStorage !== 'upload') {
            var linkA = a.link || STORAGE_UPLOAD_LINK;
            var linkB = b.link || STORAGE_UPLOAD_LINK;
            if (linkA !== linkB) {
                return linkA < linkB ? -1 : 1;
            }
            return (Number(a.message_id) || 0) - (Number(b.message_id) || 0);  // Message or comment ID, ascending.
        }
        var idA = Number(a.storage_id) || 0;
        var idB = Number(b.storage_id) || 0;
        return idB - idA;  // Uploads: sort by record ID descending within the channel, newest first.
    });
}

/* The history table is a single-layer grid: column 1 is a vertically merged channel cell, and columns 2–6 hold each record's cells.
   All records from the same channel form one group; the channel name appears once and spans all its rows (like merged cells in Excel). */
function storageCell(column, row, cls, inner, title) {
    return '<div class="storage-cell' + cls + '" data-row="' + row + '"' +
        (title ? ' title="' + escAttr(title) + '"' : '') +
        ' style="grid-column:' + column + ';grid-row:' + row + '">' + inner + '</div>';
}

function storageGroupCell(group, startRow, len) {
    var first = group[0];
    var chat = first.chat || UNGROUPED_NAME;
    var badge = len > 1 ? '<span class="storage-msg-count">' + len + ' files</span>' : '';
    var linkHtml = '';
    if (currentStorage !== 'upload') {
        var link = first.link || STORAGE_UPLOAD_LINK;  // Only downloads have real message links; uploads have none and display "Local upload".
        linkHtml = '<span class="storage-msg" title="' + escAttr(link) + '">' + esc(link) + '</span>';
    }
    return '<div class="storage-cell storage-channel-cell" style="grid-column:1;grid-row:' + startRow + ' / span ' + len + '">' +
        '<span class="fname" title="' + escAttr(chat) + '">' + esc(chat) + '</span>' +
        linkHtml +
        badge +
        '</div>';
}

/* The link column shows each member's own link: all records in an album (media group) share the task link for the entire group (pointing to its representative message),
   so replacing the message ID in that link with this row's message ID restores the member's own link.
   Comment links have a comment parameter whose value is the comment ID; replace it with this row's message ID as well (the same applies to media groups in comments).
   Preserve unrecognized link formats or links without a message ID rather than guessing how to rewrite them. */
function memberLink(rec) {
    var link = rec.link;
    if (!link) {
        return STORAGE_UPLOAD_LINK;  // Upload records have no link; display "Local upload".
    }
    var mid = rec.message_id;
    if (mid === undefined || mid === null || mid === '') {
        return link;
    }
    // Regular message link: the final segment is the message ID; replace it with this row's message ID.
    var m = String(link).match(/^(.*\/)(\d+)$/);
    if (m) {
        return m[2] === String(mid) ? link : m[1] + mid;
    }
    // Comment link: the comment parameter value is the comment ID; replace it with this row's message ID.
    m = String(link).match(/^(.*[?&]comment=)(\d+)$/);
    if (m) {
        return m[2] === String(mid) ? link : m[1] + mid;
    }
    return link;  // Preserve unrecognized formats as-is.
}

function storageRowCells(item, row, position, groupStart) {
    var state = item.state || '';
    var text = STORAGE_TEXT[state] || item.status || '—';
    var cls = STORAGE_CLASS[state] || 'status-done';
    var extra = (groupStart ? ' group-start' : '') + (position % 2 ? ' alt' : '');
    var cells = '';
    // Column 2: show the filename for downloads and the full file path for uploads (the path is more useful for local uploads).
    var nameHtml = '<span class="ficon">' + (STORAGE_ICON[item.storage_type] || '📄') + '</span>';
    if (currentStorage !== 'upload') {
        nameHtml += '<span class="fname" title="' + escAttr(item.path || item.file) + '">' + esc(item.file) + '</span>';
    } else {
        nameHtml += '<span class="fname" title="' + escAttr(item.path || item.file) + '">' + esc(item.path || item.file) + '</span>';
    }
    cells += storageCell(2, row, extra + ' cell-name', nameHtml, item.path || item.file);
    if (currentStorage !== 'upload') {
        cells += storageCell(3, row, extra + ' cell-name',
            '<span class="fname">' + esc(memberLink(item)) + '</span>',
            memberLink(item));
        cells += storageCell(4, row, extra + ' cell-size', dash(item.size));
        cells += storageCell(5, row, extra + ' cell-speed', item.message_id ? esc(item.message_id) : '—');
        cells += storageCell(6, row, extra + ' cell-remain', dash(item.type));
        cells += storageCell(7, row, extra + ' cell-status ' + cls, esc(text), item.error);
        cells += storageCell(8, row, extra + ' cell-remain', dash(item.time));
    } else {
        cells += storageCell(3, row, extra + ' cell-size', dash(item.size));
        cells += storageCell(4, row, extra + ' cell-remain', dash(item.type));
        cells += storageCell(5, row, extra + ' cell-status ' + cls, esc(text), item.error);
        cells += storageCell(6, row, extra + ' cell-remain', dash(item.time));
    }
    return cells;
}

/* History structure fingerprint: record ID + status, excluding display fields such as size.
   Rebuild the list only when the fingerprint changes, such as when a record disappears because its file was deleted or a new record is written. */
function storageStructKey(storages) {
    var parts = [];
    for (var i = 0; i < storages.length; i++) {
        parts.push(storages[i].storage_id + '|' + storages[i].state);
    }
    return parts.join(';');
}

var lastStorageKey = null;  // Fingerprint of the last rendered records; skip rebuilding when unchanged. (Initially null rather than '', otherwise an empty record list would have an empty fingerprint and be mistaken as "unchanged," so the empty state would never render.)

function buildStorageRows(storages) {
    var groups = groupStorage(storages);  // Already grouped and sorted by channel.
    var html = '';
    var row = 1;  // Grid row numbers start at 1.
    var position = 0;  // Record index in the full table, used for zebra striping.
    var g;
    var j;
    var items;
    for (g = 0; g < groups.length; g++) {
        items = groups[g];
        html += storageGroupCell(items, row, items.length);
        for (j = 0; j < items.length; j++) {
            html += storageRowCells(items[j], row + j, position, j === 0);
            position++;
        }
        row += items.length;
    }
    return html;
}

var storageAll = [];  // All records for the current type (in the order returned by the server).
var storagePage = {size: 100, index: 0};  // Pagination state: items per page (0 = unlimited) and current page.

/* History group key: group by channel, combining multiple records from the same channel (the channel name spans rows). */
function storageGroupKey(rec) {
    if (currentStorage !== 'upload') {
        if (rec.link) {
            return 'L:' + rec.link;
        }
        return 'U:' + (rec.path || ('id' + rec.storage_id));
    }
    return 'C:' + (rec.chat || UNGROUPED_NAME);
}

/* Maximum storage_id in a group, used to sort groups (newest messages first). */
function maxStorageId(arr) {
    var m = 0;
    for (var i = 0; i < arr.length; i++) {
        var id = Number(arr[i].storage_id) || 0;
        if (id > m) {
            m = id;
        }
    }
    return m;
}

/* Group records by category: downloads by message (link), uploads by channel.
   Sort all groups by their maximum storage_id in descending order (newest first); sort within each group using sortStorage. */
function groupStorage(storages) {
    var sorted = sortStorage(storages);  // Sort by channel/category first so records in the same category are adjacent.
    var groups = [];
    var index = {};
    for (var i = 0; i < sorted.length; i++) {
        var key = storageGroupKey(sorted[i]);
        var g = index[key];
        if (g === undefined) {
            g = groups.length;
            index[key] = g;
            groups.push([]);
        }
        groups[g].push(sorted[i]);
    }
    groups.sort(function (a, b) {
        return maxStorageId(b) - maxStorageId(a);
    });
    return groups;
}

/* Split records into contiguous message blocks for pagination. */
function messageBlocksOf(storages) {
    return groupStorage(storages);
}

/* Split message blocks into pages: fill up to page_size where possible, but never split a single message (album) across pages;
   if a message itself exceeds page_size, extend the current page to show it in full (the next page starts with the following message). */
function paginateGroupBlocks(blocks, pageSize) {
    var pages = [];
    if (pageSize <= 0) {  // Unlimited: put all channel blocks on one page.
        var all = [];
        for (var k = 0; k < blocks.length; k++) {
            all = all.concat(blocks[k]);
        }
        if (all.length) {
            pages.push(all);
        }
        return pages;
    }
    var page = [];
    var count = 0;
    for (var i = 0; i < blocks.length; i++) {
        var block = blocks[i];
        if (count > 0 && count + block.length > pageSize) {
            pages.push(page);  // Adding the next block would exceed the limit; finish this page and start the next block on a new page.
            page = [];
            count = 0;
        }
        page = page.concat(block);  // Add the whole block (if the page is empty and this block is oversized, extend the page to fit it).
        count += block.length;
    }
    if (page.length) {
        pages.push(page);
    }
    return pages;
}

function pageStart(pages, index) {
    var offset = 0;
    for (var p = 0; p < index; p++) {
        offset += pages[p].length;
    }
    return pages.length ? offset + 1 : 0;
}

function pageEnd(pages, index) {
    if (!pages.length) {
        return 0;
    }
    var offset = 0;
    for (var p = 0; p <= index; p++) {
        offset += pages[p].length;
    }
    return offset;
}

function renderStorage(storages) {
    storageAll = storages;
    // Do not reset the page index here: keep the current page during polling; the corresponding actions reset it when switching types or changing page size.
    renderStoragePage();
}

/* Page content fingerprint: record structure + page index + page size + current tab.
   Use the same basis for empty and non-empty states so content changes always trigger a rebuild after switching tabs. */
function storagePageKey(pageStorages) {
    return storageStructKey(pageStorages) + '#' + storagePage.index + '#' + storagePage.size + '#' + currentStorage + '#' + storageFilterKey();
}

function renderStoragePage() {
    var filtered = filterStorage(storageAll);  // Filtering layer: apply each column's conditions first, then use the existing grouping and pagination.
    var blocks = messageBlocksOf(filtered);
    var pages = paginateGroupBlocks(blocks, storagePage.size);
    var count = pages.length;
    var body = document.getElementById('storage');
    if (count === 0) {
        /* Apply fingerprint checking to the empty state and update lastStorageKey as well: otherwise, after switching to an empty tab (such as uploads with no records) and back,
           lastStorageKey would still hold the previous tab's fingerprint, making the content appear "unchanged" and skipping the rebuild;
           the download history table would remain empty until manually refreshed. */
        var emptyKey = storagePageKey([]);
        if (emptyKey !== lastStorageKey) {
            lastStorageKey = emptyKey;
            var emptyText = hasStorageFilter() ?
                (STORAGE_FILTER_EMPTY[currentStorage] || STORAGE_FILTER_EMPTY.download) :
                (STORAGE_EMPTY_TEXT[currentStorage] || STORAGE_EMPTY_TEXT.download);
            body.innerHTML = '<div class="empty">' + emptyText + '</div>';
        }
        document.getElementById('badgeStorage').textContent = storageAll.length;
        updateStoragePager(count, 0, filtered.length, blocks.length, 0, 0, storageAll.length);
        return;
    }
    if (storagePage.index >= count) {
        storagePage.index = count - 1;  // Fall back to the last page if the data shrinks.
    }
    if (storagePage.index < 0) {
        storagePage.index = 0;
    }
    var pageStorages = pages[storagePage.index];
    var key = storagePageKey(pageStorages);
    if (key !== lastStorageKey) {
        lastStorageKey = key;
        body.innerHTML = buildStorageRows(pageStorages);
    }
    document.getElementById('badgeStorage').textContent = storageAll.length;
    updateStoragePager(count, storagePage.index, filtered.length, blocks.length, pageStart(pages, storagePage.index), pageEnd(pages, storagePage.index), storageAll.length);
}

function updateStoragePager(count, index, shown, messages, start, end, total) {
    var pager = document.getElementById('storagePager');
    if (!pager) {
        return;
    }
    var cur = count ? index + 1 : 0;
    var curEl = pager.querySelector('.pager-cur');
    var totEl = pager.querySelector('.pager-total');
    var prev = document.getElementById('storagePrev');
    var next = document.getElementById('storageNext');
    var meta = document.getElementById('storagePagerMeta');
    if (curEl) {
        curEl.textContent = cur;
    }
    if (totEl) {
        totEl.textContent = count;
    }
    if (prev) {
        prev.disabled = (index <= 0);
    }
    if (next) {
        next.disabled = (index >= count - 1);
    }
    if (meta) {
        meta.textContent = (hasStorageFilter() ? 'Filtered: ' + shown + ' of ' + total : total + ' records') +
            ' · ' + messages + ' messages' + (count ? (' · This page: ' + start + '–' + end) : '');
    }
}

function goStoragePage(delta) {
    storagePage.index += delta;
    renderStoragePage();
}

/* Sync the page-size dropdown's displayed value and highlighted option without triggering a render (used during initialization). */
function applyPageSizeLabel(size) {
    var valEl = document.getElementById('storagePageSizeVal');
    if (valEl) {
        valEl.textContent = size === 0 ? 'All' : String(size);
    }
    var pop = document.getElementById('storagePageSizePop');
    if (pop) {
        var opts = pop.querySelectorAll('.pager-select-opt');
        for (var i = 0; i < opts.length; i++) {
            var s = parseInt(opts[i].getAttribute('data-size'), 10);
            opts[i].classList.toggle('active', s === size);
        }
    }
}

function setStoragePageSize(size) {
    storagePage.size = size;
    storagePage.index = 0;  // Return to the first page when the page size changes.
    saveState('storagePageSize', size);
    applyPageSizeLabel(size);
    renderStoragePage();
}

function bindStoragePager() {
    var prev = document.getElementById('storagePrev');
    var next = document.getElementById('storageNext');
    var wrap = document.getElementById('storagePageSize');
    var btn = document.getElementById('storagePageSizeBtn');
    var pop = document.getElementById('storagePageSizePop');
    if (prev) {
        prev.onclick = function () { goStoragePage(-1); };
    }
    if (next) {
        next.onclick = function () { goStoragePage(1); };
    }
    if (wrap && btn && pop) {
        var saved = parseInt(localStorage.getItem('storagePageSize'), 10);
        if (!isNaN(saved) && (saved === 0 || (saved >= 20 && saved <= 500))) {
            storagePage.size = saved;  // Restore only valid values to avoid invalid data.
        }
        applyPageSizeLabel(storagePage.size);  // Sync the display only; do not trigger a render.
        btn.onclick = function (event) {
            event.stopPropagation();
            pop.hidden = !pop.hidden;
            wrap.classList.toggle('open', !pop.hidden);
        };
        var opts = pop.querySelectorAll('.pager-select-opt');
        for (var i = 0; i < opts.length; i++) {
            opts[i].onclick = function (event) {
                event.stopPropagation();
                setStoragePageSize(parseInt(this.getAttribute('data-size'), 10));
                pop.hidden = true;
                wrap.classList.remove('open');
            };
        }
        document.addEventListener('click', function (event) {
            if (wrap.contains(event.target)) {
                return;
            }
            pop.hidden = true;
            wrap.classList.remove('open');
        });
    }
}

/* Excel-style column filtering: insert a filtering layer before grouping and pagination; when there are no filters, return the input unchanged and leave the existing flow untouched.
   Store each column's conditions independently, with AND between columns; value lists and counts reflect records visible after filtering by the other columns. */
function hasStorageFilter() {
    return Object.keys(storageFilters[currentStorage]).length > 0;
}

/* Convert bytes to a readable size using the same decimal units as backend MetaData.suitable_units_display (for example, 1.50MB),
   for the size-column filter list so the displayed values match what is filtered. */
function suitableSizeText(byte) {
    var units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
    var values = [Number(byte) || 0];
    var i;
    for (i = 0; i < units.length - 1; i++) {
        if (values[i] >= 1000) {
            values.push(values[i] / 1000);
        } else {
            break;
        }
    }
    return values[values.length - 1].toFixed(2) + units[values.length - 1];
}

/* Filter values (raw): use the same source as the cell display; the merged channel column uses the channel name, and the link column uses the link processed by memberLink;
   the size column uses bytes and the message ID uses a number for numeric comparisons in custom conditions. */
function storageFilterValue(rec, key) {
    if (key === 'chat') {
        return rec.chat || UNGROUPED_NAME;
    }
    if (key === 'file') {
        return rec.file || '';
    }
    if (key === 'path') {
        return rec.path || rec.file || '';
    }
    if (key === 'link') {
        return memberLink(rec);
    }
    if (key === 'size') {
        return Number(rec.size_byte) || 0;
    }
    if (key === 'mid') {
        return rec.message_id ? Number(rec.message_id) : 0;
    }
    if (key === 'type') {
        return rec.type || '';
    }
    if (key === 'state') {
        return STORAGE_TEXT[rec.state] || rec.status || '';
    }
    if (key === 'time') {
        return rec.time || '';
    }
    return '';
}

/* Filter display text: match the final cell display, render empty values as a dash, and format the size column in decimal units. */
function storageFilterText(rec, key) {
    if (key === 'size') {
        return suitableSizeText(rec.size_byte);
    }
    if (key === 'mid') {
        return rec.message_id ? String(rec.message_id) : '—';
    }
    var value = storageFilterValue(rec, key);
    return value === '' ? '—' : String(value);
}

function storageFilterColDef(key) {
    var cols = STORAGE_FILTER_COLS[currentStorage] || [];
    for (var i = 0; i < cols.length; i++) {
        if (cols[i].key === key) {
            return cols[i];
        }
    }
    return null;
}

function storageFilterKind(key) {
    var col = storageFilterColDef(key);
    return col ? col.kind : 'text';
}

function defaultFilterOp(kind) {
    var ops = STORAGE_FILTER_OPS[kind] || STORAGE_FILTER_OPS.text;
    return ops[0].op;
}

/* Filtering layer: intersect conditions across columns and exclude records that fail any column; return the input unchanged when there are no conditions. */
function filterStorage(storages) {
    var filters = storageFilters[currentStorage];
    var keys = Object.keys(filters);
    if (!keys.length) {
        return storages;
    }
    return storages.filter(function (rec) {
        for (var i = 0; i < keys.length; i++) {
            if (!matchStorageFilter(rec, keys[i], filters[keys[i]])) {
                return false;
            }
        }
        return true;
    });
}

function matchStorageFilter(rec, key, cond) {
    if (cond.mode === 'custom') {
        return matchCustomFilter(storageFilterValue(rec, key), storageFilterKind(key), cond);
    }
    var values = cond.values || [];
    return values.indexOf(storageFilterText(rec, key)) !== -1;
}

/* Custom-condition matching: case-insensitive text, numeric comparison by byte count, and date comparison by lexicographic order of time strings. */
function matchCustomFilter(value, kind, cond) {
    var op = cond.op;
    if (kind === 'number') {
        var num = Number(value) || 0;
        if (op === 'between') {
            return num >= (Number(cond.value) || 0) && num <= (Number(cond.value2) || 0);
        }
        if (op === 'equals') {
            return num === (Number(cond.value) || 0);
        }
        if (op === 'greater') {
            return num > (Number(cond.value) || 0);
        }
        if (op === 'less') {
            return num < (Number(cond.value) || 0);
        }
        return true;
    }
    if (kind === 'date') {
        var text = String(value);
        var from = String(cond.value || '');
        var to = String(cond.value2 || '');
        if (op === 'equals') {
            return text.indexOf(from) === 0;  // Match a date prefix: '2026-10-15' matches all records from that day.
        }
        if (op === 'after') {
            return text > from;
        }
        if (op === 'before') {
            return text < from;
        }
        if (op === 'between') {
            return to ? (text >= from && text <= to + ' 23:59:59') : text >= from;
        }
        return true;
    }
    var target = String(value).toLowerCase();
    var query = String(cond.value || '').toLowerCase();
    if (op === 'equals') {
        return target === query;
    }
    if (op === 'notEquals') {
        return target !== query;
    }
    if (op === 'contains') {
        return target.indexOf(query) !== -1;
    }
    if (op === 'notContains') {
        return target.indexOf(query) === -1;
    }
    if (op === 'begins') {
        return target.indexOf(query) === 0;
    }
    if (op === 'ends') {
        return query.length > 0 && target.length >= query.length &&
            target.lastIndexOf(query) === target.length - query.length;
    }
    return true;
}

/* Value counts for a column: count only records visible after filtering by the other columns, matching Excel's contextual-count behavior.
   Keep raw values as sort keys for numeric columns to prevent display-text sorting from placing '10.00MB' before '2.00MB'. */
function storageValueCounts(key) {
    var filters = storageFilters[currentStorage];
    var keys = Object.keys(filters);
    var entries = {};
    for (var i = 0; i < storageAll.length; i++) {
        var rec = storageAll[i];
        var visible = true;
        for (var j = 0; j < keys.length; j++) {
            if (keys[j] !== key && !matchStorageFilter(rec, keys[j], filters[keys[j]])) {
                visible = false;
                break;
            }
        }
        if (!visible) {
            continue;
        }
        var text = storageFilterText(rec, key);
        if (entries[text] === undefined) {
            entries[text] = {count: 0, raw: storageFilterValue(rec, key)};
        }
        entries[text].count++;
    }
    return entries;
}

/* Serialized fingerprint of the filters: changes to conditions must trigger a rebuild, or rendering may be skipped because the content appears unchanged. */
function storageFilterKey() {
    var filters = storageFilters[currentStorage];
    var keys = Object.keys(filters).sort();
    var parts = [];
    for (var i = 0; i < keys.length; i++) {
        var cond = filters[keys[i]];
        if (cond.mode === 'custom') {
            parts.push(keys[i] + ':' + cond.op + ':' + cond.value + ':' + cond.value2);
        } else {
            parts.push(keys[i] + ':' + (cond.values || []).join(','));
        }
    }
    return parts.join(';');
}

function saveStorageFilters() {
    saveState(STORAGE_FILTER_KEY, JSON.stringify(storageFilters));
}

/* Restore the previous filters: validate each item's structure and column key, discarding malformed entries entirely so corrupted local storage cannot break the history page. */
function loadStorageFilters() {
    var saved = {};
    try {
        saved = JSON.parse(localStorage.getItem(STORAGE_FILTER_KEY) || '{}') || {};
    } catch (e) {
        saved = {};
    }
    var tabs = ['download', 'upload'];
    for (var t = 0; t < tabs.length; t++) {
        var tab = tabs[t];
        var cols = STORAGE_FILTER_COLS[tab] || [];
        var src = saved[tab];
        var dst = {};
        if (src && typeof src === 'object') {
            for (var i = 0; i < cols.length; i++) {
                var key = cols[i].key;
                var cond = src[key];
                if (!cond || typeof cond !== 'object') {
                    continue;
                }
                if (cond.mode === 'custom') {
                    if (typeof cond.value === 'string' && cond.value !== '') {
                        dst[key] = {
                            mode: 'custom',
                            op: String(cond.op || 'contains'),
                            value: cond.value,
                            value2: String(cond.value2 || '')
                        };
                    }
                } else if (cond.mode === 'values' && Object.prototype.toString.call(cond.values) === '[object Array]') {
                    var values = [];
                    for (var j = 0; j < cond.values.length; j++) {
                        values.push(String(cond.values[j]));
                    }
                    dst[key] = {mode: 'values', values: values};
                }
            }
        }
        storageFilters[tab] = dst;
    }
}

/* Sync header filter-button active states: columns with conditions show a highlighted funnel; do not change the header structure. */
function refreshStorageFilterButtons() {
    var buttons = document.querySelectorAll('.list-storage .list-head .hfilter');
    for (var i = 0; i < buttons.length; i++) {
        var key = buttons[i].getAttribute('data-filter');
        buttons[i].classList.toggle('active', !!storageFilters[currentStorage][key]);
    }
}

/* Commit the panel's temporary state to the filters and rerender; treat an empty condition as clearing that column's filter. */
function commitStorageFilterPanel() {
    var panel = storageFilterPanel;
    var pop = storageFilterPop;
    var customView = pop ? pop.querySelector('.hfilter-custom') : null;
    var cond = null;
    if (panel.isCustom && customView && customView.hidden) {
        // Opened with a custom condition but still outside the custom editor: the checked values are display-only, so Apply keeps the original condition instead of downgrading it to values.
        cond = storageFilters[currentStorage][storageFilterCol];
    } else if (customView && !customView.hidden && panel.custom.value !== '') {
        var col = storageFilterColDef(storageFilterCol);
        var value = panel.custom.value;
        var value2 = panel.custom.value2;
        if (col && col.unit === 'MB') {  // Size-column input is in MB; convert to bytes for comparison with size_byte.
            value = String((Number(value) || 0) * FILTER_MB);
            value2 = String((Number(value2) || 0) * FILTER_MB);
        }
        cond = {mode: 'custom', op: panel.custom.op, value: value, value2: value2};
    } else if (panel.values && panel.values.length &&
        !sameStorageFilterValues(panel.values, panel.all || [])) {
        // If all visible values are checked, treat the column as unfiltered; do not save a condition and restore the arrow icon.
        cond = {mode: 'values', values: panel.values.slice()};
    }
    if (cond) {
        storageFilters[currentStorage][storageFilterCol] = cond;
    } else {
        delete storageFilters[currentStorage][storageFilterCol];
    }
    saveStorageFilters();
    closeStorageFilterPop();
    refreshStorageFilterButtons();
    storagePage.index = 0;  // Return to the first page when conditions change so the page index remains valid.
    renderStoragePage();
}

function closeStorageFilterPop() {
    if (storageFilterPop) {
        storageFilterPop.parentNode.removeChild(storageFilterPop);
    }
    storageFilterPop = null;
    storageFilterPanel = null;
    storageFilterCol = '';
    storageFilterEntries = null;  // Release the cached value set used while the panel was open.
}

/* Open a column's filter panel: copy the current condition into temporary state and commit it only on Apply; discard it on Cancel or an outside click. */
function openStorageFilterPop(button) {
    closeStorageFilterPop();
    var key = button.getAttribute('data-filter');
    storageFilterCol = key;
    storageFilterEntries = storageValueCounts(key);  // Calculate once for both matched below and fillStorageFilterValues, avoiding repeated traversal.
    var cond = storageFilters[currentStorage][key];
    if (cond && cond.mode === 'custom') {
        // For a custom-filtered column, calculate the matching values now instead of deferring the redundant matchCustom check to fillStorageFilterValues.
        var mKind = storageFilterKind(key);
        var mVals = Object.keys(storageFilterEntries);
        var mC = {op: cond.op, value: cond.value, value2: cond.value2 || ''};
        var matched = [];
        for (var mi = 0; mi < mVals.length; mi++) {
            if (matchCustomFilter(storageFilterEntries[mVals[mi]].raw, mKind, mC)) {
                matched.push(mVals[mi]);
            }
        }
        storageFilterPanel = {
            values: matched,
            custom: {op: cond.op, value: cond.value, value2: cond.value2 || ''},
            isCustom: true
        };
    } else {
        storageFilterPanel = {
            values: cond && cond.values ? cond.values.slice() : null,  // null means all values are selected (no filter).
            custom: {op: defaultFilterOp(storageFilterKind(key)), value: '', value2: ''}
        };
    }
    var pop = buildStorageFilterPop();
    storageFilterPop = pop;
    document.body.appendChild(pop);
    fillStorageFilterValues(pop);
    placeStorageFilterPop(pop, button);
    bindStorageFilterPop(pop);
}

function buildStorageFilterPop() {
    var kind = storageFilterKind(storageFilterCol);
    var col = storageFilterColDef(storageFilterCol);
    var ops = STORAGE_FILTER_OPS[kind] || STORAGE_FILTER_OPS.text;
    var argLabel = (col && col.arg) || STORAGE_FILTER_ARG_LABEL[kind] || STORAGE_FILTER_ARG_LABEL.text;
    var pop = document.createElement('div');
    pop.className = 'hfilter-pop';
    var html = '';
    html += '<div class="hfilter-search"><input type="text" class="hfilter-search-input trmd-input" placeholder="Search"></div>';
    html += '<div class="hfilter-list">';
    html += '<label class="hfilter-item hfilter-all-item"><input type="checkbox" class="hfilter-all-box">' +
        '<span class="hfilter-label">(Select all)</span></label>';
    html += '<div class="hfilter-values"></div>';
    html += '<div class="hfilter-none" hidden>No matching values</div>';
    html += '</div>';
    html += '<div class="hfilter-custom" hidden>';
    // Reuse the custom page-size dropdown structure (.pager-select) for operators instead of the browser's native select.
    html += '<div class="pager-select hfilter-op">' +
        '<button type="button" class="pager-select-btn hfilter-op-btn">' +
        '<span class="pager-select-val hfilter-op-val"></span>' +
        '<span class="pager-select-caret"></span>' +
        '</button>' +
        '<div class="pager-select-pop hfilter-op-pop" hidden>';
    for (var i = 0; i < ops.length; i++) {
        html += '<button type="button" class="pager-select-opt" data-op="' + escAttr(ops[i].op) + '">' + esc(ops[i].label) + '</button>';
    }
    html += '</div></div>';
    html += '<div class="hfilter-args">' +
        '<input type="text" class="hfilter-arg trmd-input" placeholder="' + escAttr(argLabel) + '">' +
        '<input type="text" class="hfilter-arg hfilter-arg2 trmd-input" placeholder="To" hidden>' +
        '</div>';
    html += '</div>';
    html += '<div class="hfilter-switch">' +
        '<button type="button" class="hfilter-custom-btn">' + esc(STORAGE_FILTER_CUSTOM_LABEL[kind]) + '</button></div>';
    html += '<div class="hfilter-foot">' +
        '<button type="button" class="hfilter-ok">Apply</button>' +
        '<button type="button" class="hfilter-cancel">Cancel</button></div>';
    pop.innerHTML = html;
    return pop;
}

/* Sync the custom operator dropdown's displayed value and selected state; use the matching option's label as the display text. */
function syncFilterOpDisplay(pop, op) {
    var val = pop.querySelector('.hfilter-op-val');
    var opts = pop.querySelectorAll('.hfilter-op-pop .pager-select-opt');
    var label = op;
    for (var i = 0; i < opts.length; i++) {
        var match = opts[i].getAttribute('data-op') === op;
        opts[i].classList.toggle('active', match);
        if (match) {
            label = opts[i].textContent;
        }
    }
    if (val) {
        val.textContent = label;
    }
}

/* Populate the value list: sort numeric columns by raw value and others by display text; select all by default when values is null (no filter). */
function fillStorageFilterValues(pop) {
    var valuesBox = pop.querySelector('.hfilter-values');
    var entries = storageFilterEntries || storageValueCounts(storageFilterCol);  // Reuse the cache calculated when opening the panel to avoid repeated traversal.
    var kind = storageFilterKind(storageFilterCol);
    var values = Object.keys(entries);
    values.sort(function (a, b) {
        if (kind === 'number') {
            return (Number(entries[a].raw) || 0) - (Number(entries[b].raw) || 0);
        }
        return a < b ? -1 : (a > b ? 1 : 0);
    });
    var panel = storageFilterPanel;
    panel.all = values.slice();  // All values visible when the panel opened; use this to identify no filter when all are selected again.
    if (panel.values === null) {
        panel.values = values.slice();  // No filter: select all on open (custom columns already have matched values from openStorageFilterPop and do not enter this branch).
    }
    // Custom-filtered columns: put checked (currently matching) values first and unchecked, non-matching values afterward to make the active scope clear.
    if (panel.isCustom) {
        values = values.slice().sort(function (a, b) {
            var ia = panel.values.indexOf(a) !== -1 ? 0 : 1;
            var ib = panel.values.indexOf(b) !== -1 ? 0 : 1;
            return ia - ib;
        });
    }
    var html = '';
    for (var i = 0; i < values.length; i++) {
        var value = values[i];
        var checked = panel.values.indexOf(value) !== -1 ? ' checked' : '';
        html += '<label class="hfilter-item" data-value="' + escAttr(value) + '" data-label="' + escAttr(value.toLowerCase()) + '">' +
            '<input type="checkbox"' + checked + '>' +
            '<span class="hfilter-label" title="' + escAttr(value) + '">' + esc(value) + '</span>' +
            '<span class="hfilter-count">' + entries[value].count + '</span></label>';
    }
    valuesBox.innerHTML = html;
    pop.querySelector('.hfilter-none').hidden = values.length > 0;
    syncStorageFilterAllBox(pop);
}

/* Three states for the (Select all) checkbox: checked when all are selected and indeterminate when partially selected, matching Excel. */
function syncStorageFilterAllBox(pop) {
    var allBox = pop.querySelector('.hfilter-all-box');
    var items = pop.querySelectorAll('.hfilter-values .hfilter-item');
    var shown = 0;
    var checked = 0;
    for (var i = 0; i < items.length; i++) {
        if (items[i].hidden) {
            continue;
        }
        shown++;
        if (items[i].querySelector('input').checked) {
            checked++;
        }
    }
    allBox.checked = shown > 0 && checked === shown;
    allBox.indeterminate = checked > 0 && checked < shown;
}

/* Add or remove a value from the panel's temporary state. */
function setStorageFilterValue(value, checked) {
    var values = storageFilterPanel.values;
    var at = values.indexOf(value);
    if (checked && at === -1) {
        values.push(value);
    } else if (!checked && at !== -1) {
        values.splice(at, 1);
    }
}

/* Check whether selected values exactly match all visible values, regardless of order. */
function sameStorageFilterValues(selected, all) {
    if (selected.length !== all.length) {
        return false;
    }
    var a = selected.slice().sort();
    var b = all.slice().sort();
    for (var i = 0; i < a.length; i++) {
        if (a[i] !== b[i]) {
            return false;
        }
    }
    return true;
}

/* Update checked states of visible items after a search: (Select all) applies only to currently visible items; hidden items remain unchanged. */
function toggleStorageFilterVisible(pop, checked) {
    var items = pop.querySelectorAll('.hfilter-values .hfilter-item');
    for (var i = 0; i < items.length; i++) {
        if (items[i].hidden) {
            continue;
        }
        items[i].querySelector('input').checked = checked;
        setStorageFilterValue(items[i].getAttribute('data-value'), checked);
    }
    syncStorageFilterAllBox(pop);
}

/* Panel positioning: use fixed positioning to avoid clipping while the header scrolls, right-align on right overflow, and limit maximum width on small screens. */
function placeStorageFilterPop(pop, button) {
    var rect = button.getBoundingClientRect();
    var width = pop.offsetWidth;
    var left = rect.left;
    if (left + width > window.innerWidth - 8) {
        left = window.innerWidth - width - 8;
    }
    if (left < 8) {
        left = 8;
    }
    pop.style.left = left + 'px';
    pop.style.top = (rect.bottom + 6) + 'px';
}

function bindStorageFilterPop(pop) {
    var panel = storageFilterPanel;
    var search = pop.querySelector('.hfilter-search-input');
    var valuesBox = pop.querySelector('.hfilter-values');
    var none = pop.querySelector('.hfilter-none');
    var allBox = pop.querySelector('.hfilter-all-box');
    var customView = pop.querySelector('.hfilter-custom');
    var opWrap = pop.querySelector('.hfilter-op');
    var opBtn = pop.querySelector('.hfilter-op-btn');
    var opPop = pop.querySelector('.hfilter-op-pop');
    var argInput = pop.querySelector('.hfilter-arg');
    var arg2Input = pop.querySelector('.hfilter-arg2');
    var customBtn = pop.querySelector('.hfilter-custom-btn');
    var col = storageFilterColDef(storageFilterCol);  // Filter definition for the current column, used to convert MB values when restoring the size field.
    var searchSnapshot = null;  // Snapshot of selections before searching; restore it when the search is cleared to avoid altering the original filter.
    // Validate whether Apply is enabled in custom view: between requires both values; other operators require only the first value; there are no restrictions in value-list mode.
    function syncConfirmState() {
        var ok = pop.querySelector('.hfilter-ok');
        if (!ok) {
            return;
        }
        var valid = true;
        if (customView && !customView.hidden) {
            if (panel.custom.op === 'between') {
                valid = panel.custom.value.trim() !== '' && panel.custom.value2.trim() !== '';
            } else {
                valid = panel.custom.value.trim() !== '';
            }
        }
        ok.disabled = !valid;
    }
    // Custom-filtered columns: the value list only shows which values match the condition; disable checkboxes to avoid the confusion of being able to check values without changing the filter.
    if (panel.isCustom) {
        var initItems = valuesBox.querySelectorAll('.hfilter-item');
        for (var mi = 0; mi < initItems.length; mi++) {
            var mb = initItems[mi].querySelector('input');
            if (mb) mb.disabled = true;
        }
        if (allBox) allBox.disabled = true;
        var tip = document.createElement('div');
        tip.textContent = 'Checked items match the current filter (read-only).';
        tip.style.cssText = 'font-size:11px;color:#999;padding:2px 0 4px;';
        valuesBox.insertBefore(tip, valuesBox.firstChild);
    }
    search.addEventListener('input', function () {
        var query = this.value.trim().toLowerCase();
        var shown = 0;
        var items = valuesBox.querySelectorAll('.hfilter-item');
        for (var i = 0; i < items.length; i++) {
            var label = items[i].getAttribute('data-label') || '';
            items[i].hidden = query !== '' && label.indexOf(query) === -1;
            if (!items[i].hidden) {
                shown++;
            }
        }
        none.hidden = shown > 0;
        // Filter as the user types: when a keyword is present, selection matches the visible items exactly (matching values are checked and non-matching ones are unchecked);
        // applying immediately after the search uses that condition.
        if (query !== '' && !panel.isCustom) {
            // On the first search from an empty query, save a snapshot to restore the pre-search selections when cleared.
            if (searchSnapshot === null) {
                searchSnapshot = panel.values.slice();
            }
            for (var i = 0; i < items.length; i++) {
                var visible = !items[i].hidden;
                var box = items[i].querySelector('input');
                if (box && box.checked !== visible) {
                    box.checked = visible;
                    setStorageFilterValue(items[i].getAttribute('data-value'), visible);
                }
            }
        } else if (searchSnapshot !== null) {
            // Clearing the search restores the pre-search selections instead of keeping the search subset, preventing filters such as Select all from being silently narrowed.
            for (var i = 0; i < items.length; i++) {
                var v = items[i].getAttribute('data-value');
                var should = searchSnapshot.indexOf(v) !== -1;
                var box = items[i].querySelector('input');
                if (box && box.checked !== should) {
                    box.checked = should;
                    setStorageFilterValue(v, should);
                }
            }
            searchSnapshot = null;
        }
        syncStorageFilterAllBox(pop);
    });
    allBox.addEventListener('change', function () {
        toggleStorageFilterVisible(pop, this.checked);
    });
    valuesBox.addEventListener('change', function (event) {
        var item = event.target.closest ? event.target.closest('.hfilter-item') : null;
        if (item) {
            setStorageFilterValue(item.getAttribute('data-value'), event.target.checked);
            syncStorageFilterAllBox(pop);
        }
    });
    syncFilterOpDisplay(pop, panel.custom.op);  // Initially display the current operator.
    opBtn.addEventListener('click', function (event) {
        event.stopPropagation();
        opPop.hidden = !opPop.hidden;
        opWrap.classList.toggle('open', !opPop.hidden);
    });
    var opOpts = opPop.querySelectorAll('.pager-select-opt');
    for (var i = 0; i < opOpts.length; i++) {
        opOpts[i].addEventListener('click', function (event) {
            event.stopPropagation();
            panel.custom.op = this.getAttribute('data-op');
            arg2Input.hidden = panel.custom.op !== 'between';
            syncFilterOpDisplay(pop, panel.custom.op);
            syncConfirmState();
            opPop.hidden = true;
            opWrap.classList.remove('open');
        });
    }
    argInput.addEventListener('input', function () {
        panel.custom.value = this.value.trim();
        syncConfirmState();
    });
    arg2Input.addEventListener('input', function () {
        panel.custom.value2 = this.value.trim();
        syncConfirmState();
    });
    // Advance the background doodle gradient on every filter-input keystroke, as in the login and settings dialogs (reusing the official advancement logic).
    var filterAdvance = function () {
        if (!bgCtx) {
            return;  // Skip if the gradient background did not initialize successfully.
        }
        bgAdvancePosition();
    };
    search.addEventListener('input', filterAdvance);
    argInput.addEventListener('input', filterAdvance);
    arg2Input.addEventListener('input', filterAdvance);
    customBtn.addEventListener('click', function () {
        if (customView.hidden) {
            // Value-list view: switch to custom view (keep the entry point for configuring a custom condition).
            customView.hidden = false;
            customBtn.textContent = 'Reset';
            syncFilterOpDisplay(pop, panel.custom.op);
            // Size-column input is in MB; convert stored bytes back to MB when restoring the fields so they match the input placeholders.
            argInput.value = (col && col.unit === 'MB' && panel.custom.value !== '')
                ? String((Number(panel.custom.value) || 0) / FILTER_MB) : panel.custom.value;
            arg2Input.value = (col && col.unit === 'MB' && panel.custom.value2)
                ? String((Number(panel.custom.value2) || 0) / FILTER_MB) : (panel.custom.value2 || '');
            arg2Input.hidden = panel.custom.op !== 'between';
            // Synchronize restored values: commit multiplies MB by FILTER_MB to store bytes; leaving panel.custom in bytes would multiply them a second time and inflate the value exponentially.
            panel.custom.value = argInput.value;
            panel.custom.value2 = arg2Input.value;
            syncConfirmState();  // Validate immediately on entering custom view so Apply cannot be clicked before validation.
            argInput.focus();
        } else {
            // Custom view: Reset clears this column's filter, equivalent to selecting (Select all) in the value list.
            delete storageFilters[currentStorage][storageFilterCol];
            saveStorageFilters();
            closeStorageFilterPop();
            refreshStorageFilterButtons();
            storagePage.index = 0;
            renderStoragePage();
        }
    });
    pop.querySelector('.hfilter-ok').addEventListener('click', function () {
        commitStorageFilterPanel();
    });
    pop.querySelector('.hfilter-cancel').addEventListener('click', function () {
        closeStorageFilterPop();
    });
    pop.addEventListener('click', function (event) {
        event.stopPropagation();  // Clicks inside the panel do not trigger the outside-click closing logic.
        if (opWrap && !opWrap.contains(event.target)) {  // Close the operator dropdown when clicking elsewhere in the panel.
            opPop.hidden = true;
            opWrap.classList.remove('open');
        }
    });
    // For a column that already has a custom condition, open directly in custom view and restore its values; switch to value-list view at any time.
    var cond = storageFilters[currentStorage][storageFilterCol];
    if (cond && cond.mode === 'custom') {
        customView.hidden = false;
        customBtn.textContent = 'Reset';
        syncFilterOpDisplay(pop, panel.custom.op);
        // Size-column input is in MB; convert stored bytes back to MB when restoring the fields so they match the input placeholders.
        argInput.value = (col && col.unit === 'MB' && panel.custom.value !== '')
            ? String((Number(panel.custom.value) || 0) / FILTER_MB) : panel.custom.value;
        arg2Input.value = (col && col.unit === 'MB' && panel.custom.value2)
            ? String((Number(panel.custom.value2) || 0) / FILTER_MB) : (panel.custom.value2 || '');
        arg2Input.hidden = panel.custom.op !== 'between';
        // Synchronize restored values: commit multiplies MB by FILTER_MB to store bytes; leaving panel.custom in bytes would multiply them a second time and inflate the value exponentially.
        panel.custom.value = argInput.value;
        panel.custom.value2 = arg2Input.value;
        syncConfirmState();
    }
}

/* Header filter entry point: buttons are generated dynamically by applyStorageLayout, so use delegation to bind them and keep the handler working after header rebuilds. */
function bindStorageFilters() {
    var list = document.querySelector('.list-storage');
    if (!list) {
        return;
    }
    list.addEventListener('click', function (event) {
        var button = event.target.closest ? event.target.closest('.hfilter') : null;
        if (!button) {
            return;
        }
        event.stopPropagation();  // Stop propagation to document; otherwise the newly opened panel would immediately close as an "outside click".
        openStorageFilterPop(button);
    });
    document.addEventListener('mousedown', function (event) {
        // Record whether the press began inside the panel: when dragging to select input text and releasing outside, the click
        // target is a shared ancestor (at document level); without recording the origin, the panel would close by mistake.
        storageFilterInnerDown = !!(storageFilterPop && storageFilterPop.contains(event.target));
    });
    document.addEventListener('click', function () {
        if (storageFilterInnerDown) {
            return;  // Do not close when a drag started inside the panel (such as text selection), even if released outside.
        }
        closeStorageFilterPop();  // An outside click is equivalent to Cancel; discard temporary selections.
    });
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            closeStorageFilterPop();
        }
    });
    var scroll = list.querySelector('.list-scroll');
    if (scroll) {
        scroll.addEventListener('scroll', function () {
            closeStorageFilterPop();  // Close the panel when the header scrolls out of view to prevent it becoming misaligned with the button.
        });
    }
}

/* Full-row hover: history rows have no row container, so highlight cells sharing the same grid-row number. */
function bindStorageHover() {
    var box = document.getElementById('storage');
    if (!box) {
        return;
    }
    var setRowHover = function (node, enable) {
        var cell = node && node.closest ? node.closest('.storage-cell[data-row]') : null;
        if (!cell || !box.contains(cell)) {
            return;
        }
        var cells = box.querySelectorAll('.storage-cell[data-row="' + cell.getAttribute('data-row') + '"]');
        for (var i = 0; i < cells.length; i++) {
            cells[i].classList.toggle('hover', enable);
        }
    };
    box.addEventListener('mouseover', function (event) {
        setRowHover(event.target, true);
    });
    box.addEventListener('mouseout', function (event) {
        setRowHover(event.target, false);
    });
}

async function refreshStorage() {
    refreshStorageDisk();  // Fetch the disk card separately from the list; a failure does not affect the list.
    try {
        var res = await fetch('/api/storage?type=' + encodeURIComponent(currentStorage), {cache: 'no-store', headers: authHeaders()});
        if (res.status === 401) {
            openLogin();  // Unauthenticated: show the login card, as on the progress page.
            return;
        }
        var json = await res.json();
        renderStorage(json.storage || []);
    } catch (e) {
        // Keep the existing list on fetch failure; the progress page's connection warning provides feedback.
    }
}

/* Fetch and render the history page's disk-space card: show used and total space on the disk containing the download directory. */
async function refreshStorageDisk() {
    try {
        var res = await fetch('/api/storage/disk', {cache: 'no-store', headers: authHeaders()});
        if (res.status === 401) {
            openLogin();  // Unauthenticated: show the login card, as on the progress page.
            return;
        }
        renderStorageDisk(await res.json());
    } catch (e) {
        // Keep the previous display on fetch failure; the progress page's connection warning provides feedback.
    }
}

function renderStorageDisk(data) {
    var path = document.getElementById('storageDiskPath');
    var fill = document.getElementById('storageDiskFill');
    var value = document.getElementById('storageDiskValue');
    var cachePath = document.getElementById('storageCachePath');
    var cacheValue = document.getElementById('storageCacheValue');
    data = data || {};
    path.textContent = data.directory || '—';
    path.title = path.textContent;  // Use a hover tooltip to view the full long path.
    if (data.total) {
        fill.style.width = data.percent + '%';
        value.textContent = data.used_text + ' / ' + data.total_text;
    } else {
        fill.style.width = '0%';  // Fall back to an empty state if disk reading fails; this does not affect the cache row.
        value.textContent = '—';
    }
    cachePath.textContent = data.cache_directory || '—';
    cachePath.title = cachePath.textContent;
    cacheValue.textContent = data.cache_text || '—';
}

var storageTimer = 0;  // History-page polling timer; query only while the page is visible to avoid unnecessary database access.

function startStoragePolling() {
    if (!storageTimer) {
        storageTimer = setInterval(function () {
            if (currentSection === 'storage') {
                refreshStorage();
            }
        }, STORAGE_POLL_INTERVAL_MS);
    }
}

/* Confirmation dialog matching the page style (replaces native confirm); returns Promise<boolean>. */
var confirmResolve = null;

function askConfirm(text, title) {
    return new Promise(function (resolve) {
        document.getElementById('confirmTitle').textContent = title || 'Confirm Action';
        document.getElementById('confirmText').textContent = text || '';
        confirmResolve = resolve;
        document.getElementById('confirmModal').hidden = false;
    });
}

function closeConfirm(result) {
    document.getElementById('confirmModal').hidden = true;
    if (confirmResolve) {
        var resolve = confirmResolve;
        confirmResolve = null;  // Clear it before invoking the callback to prevent re-entrant calls from interfering.
        resolve(result);
    }
}

/* Reuse the confirmation modal to show an alert: keep only the "OK" button (replacing the native alert). */
function askAlert(text, title) {
    var card = document.querySelector('#confirmModal .modal-card');
    var ok = document.getElementById('confirmOk');
    var cancel = document.getElementById('confirmCancel');
    card.classList.add('alert-card');  // Narrow it to match the proportions of the login card.
    ok.classList.remove('danger');  // An alert is not a destructive action, so the OK button does not need a red hover state.
    cancel.hidden = true;  // Alerts do not need a cancel button.
    return askConfirm(text, title).then(function (result) {
        card.classList.remove('alert-card');
        ok.classList.add('danger');  // Restore it so this does not affect the later "Remove listener" confirmation.
        cancel.hidden = false;
        return result;
    });
}

// ESC closes the confirmation/alert modal, just like cancel.
function confirmEscape(event) {
    if (event.key !== 'Escape') {
        return;
    }
    if (document.getElementById('confirmModal').hidden) {
        return;  // Do nothing when it is closed, to avoid affecting other modals.
    }
    closeConfirm(false);
    /* Stop later listeners on the same node (document), such as settingsEscape, from handling this ESC:
       after this function closes the alert modal, later listeners see confirmModal.hidden === true
       and may mistake it for "no alert modal," also closing the settings modal underneath. */
    event.stopImmediatePropagation();
}

function bindConfirm() {
    document.getElementById('confirmOk').onclick = function () {
        closeConfirm(true);
    };
    document.getElementById('confirmCancel').onclick = function () {
        closeConfirm(false);
    };
    document.getElementById('confirmClose').onclick = function () {
        closeConfirm(false);
    };
    document.getElementById('confirmModal').onclick = function (event) {
        if (event.target === this) {
            closeConfirm(false);  // Clicking the empty area of the overlay is equivalent to cancel.
        }
    };
    document.addEventListener('keydown', confirmEscape);
}

/* Login card: replaces the browser's native Basic authentication dialog and uses the page's frosted-glass style. */

/* When "Stay logged in for 30 days" is unchecked, store the token only in sessionStorage:
   closing the tab clears it, so the user must log in again next time.
   A cookie cannot expire when the tab closes (a session cookie is cleared only after the entire browser exits),
   so the server does not issue a cookie when unchecked; the frontend sends the token with each request instead. */
function setSessionToken(token) {
    try {
        if (token) {
            sessionStorage.setItem('trmd_token', token);
        } else {
            sessionStorage.removeItem('trmd_token');
        }
    } catch (e) {
        // Ignore cases where sessionStorage is unavailable, such as private browsing.
    }
}

function authHeaders() {
    var token = '';
    try {
        token = sessionStorage.getItem('trmd_token') || '';
    } catch (e) {
        token = '';
    }
    return token ? {Authorization: 'Bearer ' + token} : {};
}

/* Log out: notify the server to rotate the token and clear the cookie, then return to the login card. */
async function logout() {
    var dropdown = document.getElementById('menuDropdown');
    if (dropdown) {
        dropdown.hidden = true;  // Close the menu first to avoid overlapping the confirmation dialog.
    }
    var ok = await askConfirm('You will need to enter your username and password again.', 'Log Out');
    if (!ok) {
        return;
    }
    try {
        await fetch('/api/logout', {
            method: 'POST',
            headers: Object.assign({'Content-Type': 'application/json'}, authHeaders())
        });
    } catch (e) {
        // Clear local state even if the request fails to avoid leaving the interface in a logged-in state.
    }
    setSessionToken('');  // Clear the temporary token used when "Stay logged in" was unchecked.
    openLogin();  // Show the login card again and hide the page content.
}

function initLogout() {
    if (document.body.getAttribute('data-auth') !== '1') {
        return;  // No logout entry is needed when no password is configured.
    }
    var btn = document.getElementById('btnLogout');
    if (!btn) {
        return;
    }
    btn.hidden = false;
    btn.onclick = logout;
}

var loginShown = false;

function openLogin() {
    if (loginShown) {
        return;  // Polling triggers this every second; do not reopen it if it is already visible.
    }
    loginShown = true;
    document.getElementById('loginPass').value = '';
    document.getElementById('loginModal').hidden = false;
    document.body.classList.add('logged-out');  // Hide page cards while logged out, leaving only the gradient background.
    var user = document.getElementById('loginUser');
    if (user.value) {
        document.getElementById('loginPass').focus();
    } else {
        user.focus();
    }
}

function closeLogin() {
    loginShown = false;
    document.getElementById('loginModal').hidden = true;
    document.body.classList.remove('logged-out');  // Restore the page content.
}

async function submitLogin() {
    var remember = document.getElementById('loginRemember').checked;
    try {
        var res = await fetch('/api/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                username: document.getElementById('loginUser').value,
                password: document.getElementById('loginPass').value,
                remember: document.getElementById('loginRemember').checked
            })
        });
        var data = await res.json();
        if (!data.status) {
            await askAlert('Incorrect username or password. Please try again.', 'Login Failed');
            return;
        }
        // When "Stay logged in for 30 days" is checked, the server has issued a cookie; otherwise keep the token in this tab.
        setSessionToken(remember ? '' : (data.token || ''));
        // Clear fingerprints to ensure a redraw and list rebuild after login (otherwise unchanged data would be skipped).
        lastRenderKey = '';
        lastStructKey = null;
        lastUploadStructKey = null;
        closeLogin();
        if (data.first_login) {
            openSupport();  // Preserve the existing behavior of showing the support-author card on first login.
        }
        refresh();
    } catch (e) {
        await askAlert('Unable to connect to TRMD. Please try again later.', 'Login Failed');
    }
}

function bindLogin() {
    document.getElementById('loginSubmit').onclick = submitLogin;
    var user = document.getElementById('loginUser');
    var pass = document.getElementById('loginPass');
    user.onkeydown = function (event) {
        if (event.key === 'Enter') {
            pass.focus();
        }
    };
    pass.onkeydown = function (event) {
        if (event.key === 'Enter') {
            submitLogin();
        }
    };
    // Advance the gradient by one step for each character typed, reusing the official logic for advancing when sending a message.
    var advance = function () {
        if (!bgCtx) {
            return;  // Skip if the gradient background did not initialize successfully.
        }
        bgAdvancePosition();
    };
    user.addEventListener('input', advance);
    pass.addEventListener('input', advance);
}

var removingListener = {};  // Listeners awaiting confirmation or removal, preventing duplicate clicks from being processed.

async function removeListener(kind, link) {
    if (!link || removingListener[link]) {
        return;  // This listener is already awaiting confirmation or being processed; ignore duplicate clicks.
    }
    removingListener[link] = true;
    var ok = await askConfirm('Remove this listener?\n' + link, 'Remove Listener');
    if (!ok) {
        delete removingListener[link];
        return;
    }
    try {
        var res = await fetch('/api/listener/remove', {
            method: 'POST',
            headers: Object.assign({'Content-Type': 'application/json'}, authHeaders()),
            body: JSON.stringify({kind: kind, link: link})
        });
        var data = await res.json();
        if (!data.status) {
            window.alert('Failed to remove listener: ' + (data.e_code || 'Unknown error.'));
        }
    } catch (e) {
        window.alert('Failed to remove listener: Unable to connect to TRMD.');
    }
    delete removingListener[link];
    refresh();  // Refresh immediately after removal instead of waiting for the next poll.
}

async function setPause(paused) {
    try {
        var res = await fetch('/api/pause', {
            method: 'POST',
            headers: Object.assign({'Content-Type': 'application/json'}, authHeaders()),
            body: JSON.stringify({paused: paused})
        });
        var data = await res.json();
        if (!data.status) {
            window.alert('Action failed: ' + (data.e_code || 'Unknown error.'));
        }
    } catch (e) {
        window.alert('Action failed: Unable to connect to TRMD.');
    }
    // Optimistic update: the server switches the flag asynchronously through its event loop, so an immediate
    // refresh may still return the old snapshot. This would leave the button text and lastPaused one poll behind,
    // preventing the state from being toggled back during that interval. Use this request's target state directly
    // instead of waiting for the next poll response.
    lastPaused = paused;
    renderPauseState(paused);
    refresh();  // Refresh the snapshot after switching to synchronize with the backend state.
}

function renderPauseState(isPaused) {
    var btn = document.getElementById('btnPause');
    if (!btn) {
        return;  // Skip if the page does not include a pause button.
    }
    // U+FE0F renders the icons as colored emoji (⏸️ / ▶️); both glyphs have the same height,
    // This avoids top-bar height shifts and moving the cards below it.
    btn.textContent = isPaused ? '▶\uFE0F Resume' : '⏸\uFE0F Pause';
    btn.classList.toggle('paused', !!isPaused);
}

function uploadDone(file) {
    return file.state === 'success' || file.state === 'sent';
}

// Sort priority for pinning active tasks to the top when no filter is applied:
// in progress (downloading/uploading) > queued (pending) > completed/skipped (success/sent/skip) > failed (failure).
// Sort a copy of the array without modifying the backend snapshot; this is a stable sort, so tasks with equal rank keep their order.
function stateRank(state) {
    if (state === 'downloading' || state === 'uploading') {
        return 0;
    }
    if (state === 'pending') {
        return 1;
    }
    if (state === 'success' || state === 'sent' || state === 'skip') {
        return 2;
    }
    return 3;  // Put failure and other failed states at the bottom.
}

function getUploadGroups(tasks) {
    var groups = [];  // Group uploads by channel, preserving the order in which channels first appear.
    var index = {};
    var i;
    for (i = 0; i < tasks.length; i++) {
        var channel = tasks[i].channel || UNGROUPED_NAME;
        if (index[channel] === undefined) {
            index[channel] = groups.length;
            groups.push({channel: channel, name: tasks[i].chat || channel, files: []});
        }
        groups[index[channel]].files.push(tasks[i]);
    }
    for (i = 0; i < groups.length; i++) {
        var group = groups[i];
        group.count = group.files.length;
        group.complete = 0;
        group.failed = 0;
        group.total_byte = 0;
        group.done_byte = 0;
        for (var j = 0; j < group.files.length; j++) {
            var file = group.files[j];
            if (file.state === 'failure') {
                group.failed += 1;
                continue;  // Exclude failed files from the group progress denominator so they do not lower progress.
            }
            var size = Number(file.size_byte) || 0;
            group.total_byte += size;
            if (uploadDone(file)) {
                group.complete += 1;
                group.done_byte += size;
            } else {
                group.done_byte += Math.min(Number(file.completed) || 0, size);  // Count bytes already sent for files that are uploading.
            }
        }
        group.percent = group.total_byte ?
            Math.round(group.done_byte / group.total_byte * 1000) / 10 : 0;
        group.stat = groupStat(group.files, {});
    }
    return groups;
}

function uploadSummary(tasks) {
    var total = 0;  // Count only non-failed uploads in the total; failed files are excluded from the progress denominator.
    var done = 0;
    var speed = 0;
    for (var i = 0; i < tasks.length; i++) {
        var file = tasks[i];
        if (file.state === 'failure') {
            continue;  // Exclude failed files from totals and speed so they do not lower progress.
        }
        var size = Number(file.size_byte) || 0;
        total += size;
        if (uploadDone(file)) {
            done += size;
        } else if (file.state === 'uploading') {
            done += Math.min(Number(file.completed) || 0, size);  // Count bytes already sent for files that are uploading.
        }
        speed += Number(file.speed_value) || 0;
    }
    var remaining = speed && total > done ? (total - done) / speed : null;
    return {
        percent: total ? Math.round(done / total * 1000) / 10 : 0,
        info: sizeText(done) + '/' + sizeText(total),
        speed: speed ? sizeText(speed) + '/s' : '',
        remaining: remaining === null ? '' : secondsText(remaining)
    };
}

function uploadCount(tasks) {
    var count = {success: 0, failure: 0, uploading: 0, pending: 0, active: 0};
    for (var i = 0; i < tasks.length; i++) {
        var state = tasks[i].state;
        if (state === 'failure') {
            count.failure += 1;
        } else if (uploadDone(tasks[i])) {
            count.success += 1;
        } else {
            count.active += 1;
            if (state === 'uploading') {
                count.uploading += 1;
            } else {
                count.pending += 1;
            }
        }
    }
    return count;
}

function uploadRow(file) {
    var state = file.state || 'pending';
    var text = UPLOAD_TEXT[state] || 'Queued';
    var cls = UPLOAD_CLASS[state] || 'status-pending';
    var progress;
    if (uploadDone(file)) {
        progress = progressCell(100);
    } else if (state === 'uploading') {
        progress = progressCell(file.percent || 0);
    } else {
        progress = '<span class="cell-progress"><span class="pct' +
            (state === 'pending' ? ' pending' : '') + '">' + text + '</span></span>';
    }
    // data-upload-id enables in-place progress updates when the upload list structure is unchanged, avoiding a full rebuild every second.
    return '<div class="task-row member-row" data-upload-id="' +
        escAttr(file.task_id || file.path || file.file) + '">' +
        '<span class="cell-name"><span class="ficon">' + (UPLOAD_ICON[state] || '⏳') + '</span>' +
        '<span class="fname" title="' + escAttr(file.path || file.file) + '">' + esc(file.path || file.file) + '</span></span>' +
        progress +
        '<span class="cell-size">' + dash(file.size) + '</span>' +
        '<span class="cell-speed">' + dash(file.speed) + '</span>' +
        '<span class="cell-remain">' + dash(file.remaining) + '</span>' +
        '<span class="cell-status ' + cls + '" title="' + escAttr(file.error) + '">' + text + '</span>' +
        '</div>';
}

function uploadStatusCell(group) {
    if (group.failed) {
        return '<span class="cell-status status-failed">' + group.failed + ' failed</span>';
    }
    if (group.complete === group.count) {
        return '<span class="cell-status status-done">Complete</span>';
    }
    return '<span class="cell-status status-running">Uploading</span>';
}

function uploadBlock(group) {
    var key = 'upload:' + group.channel;
    var filtering = Boolean(statFilter.upload);
    var files = group.files;
    if (filtering) {
        files = files.filter(function (file) {
            return matchUploadState(file, statFilter.upload);
        });
        if (files.length === 0) {
            return '';  // Hide this group when no files match the filter.
        }
    } else {
        // With no card filter, sort by status: in progress > queued > completed/skipped > failed, keeping active tasks at the top.
        files = files.slice().sort(function (a, b) {
            return stateRank(a.state) - stateRank(b.state);
        });
    }
    // Force groups open while filtering; otherwise collapsed state would hide the results.
    var isCollapsed = filtering ? false : (collapsed[key] === undefined ? lastUploadCollapsed : collapsed[key]);
    var html = '<div class="group' + (isCollapsed ? '' : ' open') + '" data-channel="' + escAttr(key) + '" data-level="1">' +
        '<div class="group-head" data-channel="' + escAttr(key) + '">' +
        '<span class="cell-name"><span class="arrow"></span>' +
        '<span class="ficon">📺</span>' +
        '<span class="gname" title="' + escAttr(group.name) + '">' + esc(group.name) + '</span>' +
        '<span class="gcount">' + group.count + ' files</span></span>' +
        progressCell(group.percent) +
        '<span class="cell-size">' + group.complete + '/' + group.count + '</span>' +
        groupStatCells(group.stat) +
        uploadStatusCell(group) +
        '</div>' +
        '<div class="group-body"' + (isCollapsed ? ' style="display:none"' : '') + '>';
    for (var i = 0; i < files.length; i++) {
        html += uploadRow(files[i]);
    }
    return html + '</div></div>';
}

function uploadList(tasks) {
    if (tasks.length === 0) {
        return '<div class="empty">No upload tasks yet.</div>';
    }
    var html = '';
    var groups = getUploadGroups(tasks);  // Channel > full file path; the first level is collapsible.
    for (var i = 0; i < groups.length; i++) {
        html += uploadBlock(groups[i]);
    }
    if (statFilter.upload && !html) {
        return '<div class="empty">' + (UPLOAD_EMPTY_TEXT[statFilter.upload] || 'No files match the current filter.') + '</div>';
    }
    return html;
}

function syncUploadHeads() {
    var list = document.getElementById('upload');
    if (!list || !list.parentNode) {
        return;
    }
    var head = list.parentNode.querySelector('.list-head');
    var level = 1;
    var nodes = list.querySelectorAll('.group.open');
    for (var i = 0; i < nodes.length; i++) {
        if (groupVisible(nodes[i])) {
            level = 2;  // If any channel is expanded, the innermost level is the file row.
            break;
        }
    }
    head.querySelector('.h-name .htext').textContent = UPLOAD_HEAD_NAME[level - 1];
    head.querySelector('.h-size .htext').textContent = UPLOAD_HEAD_SIZE[level - 1];
}

function renderUpload(uploads) {
    var count = uploadCount(uploads);
    document.getElementById('badgeUpload').textContent = count.active;
    /* Rebuild the DOM only when the structure changes (files added/removed or status changes); otherwise update progress in place to avoid rebuilding the entire table every second. */
    var uploadKey = uploadStructKey(uploads);
    if (uploadKey !== lastUploadStructKey) {
        lastUploadStructKey = uploadKey;
        /* Determine the empty state by whether any upload files exist (including completed ones), not by whether there are active tasks.
           Otherwise, after all uploads finish count.active becomes 0 and the empty state hides all completed files
           until a new task is created. */
        // When filtering, show the specific filter criteria if nothing matches instead of the generic "No upload tasks yet.".
        var uploadEmpty = 'No upload tasks yet.';
        if (statFilter.upload) {
            uploadEmpty = UPLOAD_EMPTY_TEXT[statFilter.upload] || uploadEmpty;
        }
        document.getElementById('upload').innerHTML = uploads.length > 0 ? uploadList(uploads) : '<div class="empty">' + uploadEmpty + '</div>';
        syncToggleUpload();
        syncUploadHeads();
        bindGroups();  // Bind collapse events after the upload list has been rendered.
    } else {
        updateUploadRows(uploads);
    }
    renderOverall(uploadSummary(uploads), count.active, SUMMARY_IDS.upload);
    lastUploadFinished = count.success + count.failure;
    renderStat('uploadStat', [
        statCell('Completed', count.success, 'ok', 'success', 'upload'),
        statCell('Failed', count.failure, 'bad', 'failure', 'upload'),
        statCell('Uploading', count.uploading, '', 'uploading', 'upload'),
        statCell('Queued', count.pending, 'skip', 'pending', 'upload')
    ]);
    return count.active;
}

var lastRenderKey = '';  // Fingerprint of the previous render, used to skip redraws when nothing has changed.
var lastStructKey = null;  // List structure fingerprint; the list DOM is not rebuilt if the structure is unchanged. (Start with null, not '', or an empty link makes structKeyOf return '' and is mistaken for "unchanged," skipping the initial renderList and leaving only the list header.)
var lastUploadStructKey = null;  // Upload list structure fingerprint; same reasoning as above.

/* Polling interval in milliseconds; default is 1 second.
   If the device is under noticeable load, increase this to 2000–3000 to cut fetching and rendering overhead by more than half,
   at the cost of slower numeric updates. */
var POLL_INTERVAL_MS = 1000;

/* Upload list structure fingerprint: file path + status; excludes values that change each second, such as progress and speed. */
function uploadStructKey(uploads) {
    var parts = [];
    for (var i = 0; i < (uploads || []).length; i++) {
        parts.push((uploads[i].path || uploads[i].file || '') + '|' + uploads[i].state);
    }
    return parts.join(';');
}

/* When the upload list structure is unchanged, update each row's progress and speed text in place without rebuilding the DOM. */
function updateUploadRows(uploads) {
    var live = {};
    var i;
    for (i = 0; i < (uploads || []).length; i++) {
        live[String(uploads[i].task_id || uploads[i].path || uploads[i].file)] = uploads[i];
    }
    var rows = document.querySelectorAll('#upload [data-upload-id]');
    for (i = 0; i < rows.length; i++) {
        var row = rows[i];
        var file = live[row.getAttribute('data-upload-id')];
        if (!file) {
            continue;
        }
        var percent = uploadDone(file) ? 100 : (Number(file.percent) || 0);
        var fill = row.querySelector('.fill');
        if (fill) {
            fill.style.width = percent + '%';  // Horizontal bar on desktop.
            var cell = fill.closest('.cell-progress');  // The mobile ring depends on --p, so update it too.
            if (cell) {
                cell.style.setProperty('--p', percent + '%');
            }
        }
        var pct = row.querySelector('.pct');
        if (pct && fill) {
            pct.textContent = percent + '%';
        }
        var speed = row.querySelector('.cell-speed');
        if (speed) {
            speed.textContent = dash(file.speed);
        }
        var remain = row.querySelector('.cell-remain');
        if (remain) {
            remain.textContent = dash(file.remaining);
        }
    }
}

/* List structure fingerprint: channel, link, member name, and status.
   Intentionally excludes values that change each second, such as progress and speed, or every poll would trigger a rebuild. */
function structKeyOf(data) {
    var parts = [];
    var links = data.links || [];
    for (var i = 0; i < links.length; i++) {
        var members = links[i].queue || [];
        var sig = [];
        for (var j = 0; j < members.length; j++) {
            sig.push(members[j].name + '|' + members[j].state);
        }
        parts.push(links[i].link + '#' + sig.join(','));
    }
    return parts.join(';');
}

/* When the structure is unchanged, update only the "downloading" rows in place:
   change widths and text to avoid rebuilding the entire table DOM (only these rows are rearranged). */
function updateTaskRows(data) {
    var tasks = data.tasks || [];
    var live = {};
    var i;
    for (i = 0; i < tasks.length; i++) {
        live[String(tasks[i].id)] = tasks[i];
    }
    var rows = document.querySelectorAll('#download [data-task-id]');
    for (i = 0; i < rows.length; i++) {
        var row = rows[i];
        var task = live[row.getAttribute('data-task-id')];
        if (!task) {
            continue;  // This task has finished; replace the whole row when the structure changes.
        }
        var fill = row.querySelector('.fill');
        if (fill) {
            var pct = task.percent + '%';
            fill.style.width = pct;  // Horizontal bar on desktop.
            var cell = fill.closest('.cell-progress');  // The mobile ring depends on --p, so update it too.
            if (cell) {
                cell.style.setProperty('--p', pct);
            }
        }
        var pct = row.querySelector('.pct');
        if (pct) {
            pct.textContent = task.percent + '%';
        }
        var size = row.querySelector('.cell-size');
        if (size) {
            size.textContent = dash(task.info);
        }
        var speed = row.querySelector('.cell-speed');
        if (speed) {
            speed.textContent = dash(task.speed);
        }
        var remain = row.querySelector('.cell-remain');
        if (remain) {
            remain.textContent = dash(task.remaining);
        }
    }
}

function render(data, force) {
    /* Skip redrawing the whole page when the data has not changed.
       Previously, the entire list DOM was rebuilt every second, invalidating all frosted-glass layers and resampling the background;
       this was the main source of GPU usage. When idle (with no task changes), this overhead can be eliminated entirely. */
    var key = JSON.stringify(data);
    if (!force && key === lastRenderKey) {
        return;
    }
    lastRenderKey = key;
    connectionStatus = data.connection_status || '';
    var downloads = (data.tasks || []).length;
    lastDownloadActive = downloads;
    document.getElementById('badgeDownload').textContent = downloads;
    // Overall progress and stats cards belong to the download page, and summary is sent per section. Skip rendering outside the download section
    // to avoid setting hidden panels to 0% and to prevent unnecessary writes to hidden elements every second.
    if (currentSection === 'download') {
        renderOverall(data.summary, downloads, SUMMARY_IDS.download);
        renderStat('stat', [
            statCell('Completed', data.count.success, 'ok', 'success', 'download'),
            statCell('Failed', data.count.failure, 'bad', 'failure', 'download'),
            statCell('Skipped', data.count.skip, 'skip', 'skip', 'download'),
            statCell('Downloading', downloads, '', 'active', 'download'),
            statCell('Queued', countQueueMembers(data.links), 'queue', 'queue', 'download')
        ]);
    }
    lastUploadActive = renderUpload(data.uploads || []);
    lastListenCount = renderListeners(data.listeners);
    if (currentSection === 'notice') {
        renderNotices(data.notices);  // Notices are sent only for the notices section; a new notice changes the fingerprint and triggers a redraw.
    }
    lastPaused = !!data.is_paused;
    renderPauseState(lastPaused);
    renderOuterLinks(data.outer_links);
    renderStatus();
    // Rebuild the DOM only when the list structure changes (members added/removed or status changes);
    // otherwise, update only the downloading rows in place to avoid reflow and repaint from rebuilding the full table every second.
    // links are sent only for the download section; skip other sections so hidden download lists are not rendered as empty.
    if (currentSection === 'download') {
        var structKey = structKeyOf(data);
        if (structKey !== lastStructKey) {
            lastStructKey = structKey;
            renderList(data);
        } else {
            updateTaskRows(data);
        }
    }
    syncBackgroundProgress(data.count.success + data.count.failure + data.count.skip + lastUploadFinished);
}

function syncBackgroundProgress(finished) {  // Advance the background gradient once per completed download or upload, matching the official behavior when a message is sent.
    if (bgLastProgress < 0) {
        bgLastProgress = finished;  // On the first call, record the baseline without advancing.
        return;
    }
    if (finished > bgLastProgress) {
        bgLastProgress = finished;
        bgAdvancePosition();
    }
    if (finished < bgLastProgress) {
        bgLastProgress = finished;  // Sync the baseline when tasks are cleared or reset to avoid a false trigger if the count decreases.
    }
}

async function refresh(force) {
    try {
        // section tells the server which section is active: links (the member array) and notices are sent per section, avoiding needless transfers every second on other sections.
        var res = await fetch('/api/progress?section=' + currentSection, {cache: 'no-store', headers: authHeaders()});
        if (res.status === 401) {
            openLogin();  // Unauthenticated: show the login card instead of triggering a native browser dialog.
            return;
        }
        document.body.classList.remove('logged-out');  // Authentication succeeded; show the page content.
        var json = await res.json();
        lastSnapshot = json;  // Cache the latest snapshot to prefill the save directory in the settings modal.
        render(json, force);
        refreshNameTip();  // After the list is redrawn, reposition the tooltip based on the current mouse location.
        document.getElementById('offline').style.display = 'none';
    } catch (e) {
        document.getElementById('offline').style.display = 'block';
    }
}

function bindSections() {
    var items = document.querySelectorAll('.side-item');
    for (var i = 0; i < items.length; i++) {
        items[i].onclick = function () {
            switchSection(this.getAttribute('data-section'));
        };
    }
}

function bindPause() {
    var btn = document.getElementById('btnPause');
    if (!btn) {
        return;  // Skip binding if the page does not include a pause button.
    }
    btn.onclick = function () {
        setPause(!lastPaused);  // Use the currently displayed state; clicking again toggles pause/resume.
    };
}

function bindListenTabs() {
    var tabs = document.querySelectorAll('#listenTabs .tab');
    for (var i = 0; i < tabs.length; i++) {
        tabs[i].onclick = function () {
            switchListen(this.getAttribute('data-listen'));
        };
    }
}

function bindListenRemove() {
    var box = document.getElementById('page-listener');  // Use event delegation to avoid rebinding on every poll.
    box.onclick = function (event) {
        var target = event.target;
        if (!target || !target.classList || !target.classList.contains('btn-del')) {
            return;
        }
        removeListener(target.getAttribute('data-kind'), target.getAttribute('data-link'));
    };
}

function openSupport() {
    document.getElementById('supportModal').hidden = false;
}

function closeSupport() {
    document.getElementById('supportModal').hidden = true;
}

function supportEscape(event) {
    if (event.key === 'Escape' && !document.getElementById('supportModal').hidden) {
        closeSupport();
    }
}

function initSettings() {
    var btn = document.getElementById('btnSettings');
    if (btn) {
        btn.onclick = openSettings;
    }
    var close = document.getElementById('settingsClose');
    if (close) {
        close.onclick = closeSettings;
    }
    var cancel = document.getElementById('saveDirCancel');
    if (cancel) {
        cancel.onclick = closeSettings;
    }
    var apply = document.getElementById('saveDirApply');
    if (apply) {
        apply.onclick = applyConfig;
    }
    document.addEventListener('keydown', settingsEscape);  // ESC closes the modal (clicking the overlay no longer closes it).
    // Advance the background doodle gradient with each keystroke while editing settings, as in the login form (reusing the official progression logic).
    var cfgAdvance = function () {
        if (!bgCtx) {
            return;  // Skip if the gradient background was not initialized successfully.
        }
        bgAdvancePosition();
    };
    ['saveDirInput', 'maxDownload', 'maxUpload', 'maxRetryDownload', 'maxRetryUpload'].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', cfgAdvance);
        }
    });
}

var settingsOriginal = null;  // Snapshot of original values when the settings modal opens, used to "submit changed items only" instead of saving everything.

function openSettings() {
    setMenuOpen(false);  // Close the top menu first to avoid overlapping it with the settings modal.
    var modal = document.getElementById('settingsModal');
    if (lastSnapshot) {
        if (lastSnapshot.save_directory) {
            document.getElementById('saveDirInput').value = lastSnapshot.save_directory;
        }
        setNum('maxDownload', lastSnapshot.max_tasks && lastSnapshot.max_tasks.download);
        setNum('maxUpload', lastSnapshot.max_tasks && lastSnapshot.max_tasks.upload);
        setNum('maxRetryDownload', lastSnapshot.max_retries && lastSnapshot.max_retries.download);
        setNum('maxRetryUpload', lastSnapshot.max_retries && lastSnapshot.max_retries.upload);
    }
    /* When no bot is configured (HAS_BOT), changes to upload concurrency/retries have no effect; hide these options to avoid misleading the user. */
    var uploadAvailable = HAS_BOT;
    ['maxUpload', 'maxRetryUpload'].forEach(function (id) {
        var el = document.getElementById(id);
        if (el && el.parentElement) {
            el.parentElement.style.display = uploadAvailable ? '' : 'none';
        }
    });
    /* Record the values in the inputs when the modal opens as the comparison baseline (lastSnapshot alone becomes stale as polling updates it). */
    settingsOriginal = {
        save_directory: (document.getElementById('saveDirInput').value || '').trim(),
        max_tasks: {download: numVal('maxDownload'), upload: numVal('maxUpload')},
        max_retries: {download: numVal('maxRetryDownload'), upload: numVal('maxRetryUpload')}
    };
    modal.hidden = false;
}

function closeSettings() {
    document.getElementById('settingsModal').hidden = true;
}

function settingsEscape(event) {
    if (event.key !== 'Escape') {
        return;
    }
    // If an alert/confirmation modal is open, confirmEscape has already handled ESC (stopImmediatePropagation normally prevents it reaching here);
    // if it is still detected here, exit without also closing the settings modal.
    if (!document.getElementById('confirmModal').hidden) {
        return;
    }
    if (!document.getElementById('settingsModal').hidden) {
        closeSettings();
    }
}

/* Conflict detection: lastSnapshot is refreshed by background polling every second, while settingsOriginal is the baseline from when the modal opened.
   If an item being submitted was changed elsewhere, submitting would overwrite that change, so return the conflicting items for confirmation;
   items not being submitted will not be overwritten even if they changed, so check only the items actually being changed.
   This is a separate function so it can be called before the initial submission and again before the post-confirmation submission,
   preventing changes made elsewhere while the confirmation is open from being overwritten with stale values. */
function checkConfigConflict(dirChanged, tasksChanged, retriesChanged, lastSnapshot, settingsOriginal) {
    var conflictParts = [];
    if (dirChanged && lastSnapshot && settingsOriginal
        && (lastSnapshot.save_directory || '') !== settingsOriginal.save_directory) {
        conflictParts.push('save directory');
    }
    if (tasksChanged && lastSnapshot && lastSnapshot.max_tasks && settingsOriginal
        && (lastSnapshot.max_tasks.download !== settingsOriginal.max_tasks.download
            || lastSnapshot.max_tasks.upload !== settingsOriginal.max_tasks.upload)) {
        conflictParts.push('concurrency');
    }
    if (retriesChanged && lastSnapshot && lastSnapshot.max_retries && settingsOriginal
        && (lastSnapshot.max_retries.download !== settingsOriginal.max_retries.download
            || lastSnapshot.max_retries.upload !== settingsOriginal.max_retries.upload)) {
        conflictParts.push('retry count');
    }
    return conflictParts;
}

/* After a conflict is canceled, refill the modal with the latest backend settings and refresh the comparison baseline. Otherwise, the modal still shows stale values,
   and the user may hit the same conflict by clicking Apply again without knowing the settings changed elsewhere; after refilling, the modal matches the backend and Apply reports "no changes." */
function syncSettingsFromSnapshot() {
    if (!lastSnapshot) {
        return;
    }
    var dirInput = document.getElementById('saveDirInput');
    if (dirInput && lastSnapshot.save_directory) {
        dirInput.value = lastSnapshot.save_directory;
    }
    if (lastSnapshot.max_tasks) {
        setNum('maxDownload', lastSnapshot.max_tasks.download);
        setNum('maxUpload', lastSnapshot.max_tasks.upload);
    }
    if (lastSnapshot.max_retries) {
        setNum('maxRetryDownload', lastSnapshot.max_retries.download);
        setNum('maxRetryUpload', lastSnapshot.max_retries.upload);
    }
    settingsOriginal = {
        save_directory: lastSnapshot.save_directory,
        max_tasks: lastSnapshot.max_tasks ? {
            download: lastSnapshot.max_tasks.download,
            upload: lastSnapshot.max_tasks.upload
        } : {download: null, upload: null},
        max_retries: lastSnapshot.max_retries ? {
            download: lastSnapshot.max_retries.download,
            upload: lastSnapshot.max_retries.upload
        } : {download: null, upload: null}
    };
}

async function applyConfig() {
    var dirInput = document.getElementById('saveDirInput');
    var path = (dirInput.value || '').trim();
    if (!path) {
        await askAlert('The save directory cannot be empty.', 'Edit Settings');
        return;
    }
    var maxTasks = {download: numVal('maxDownload'), upload: numVal('maxUpload')};
    var maxRetries = {download: numVal('maxRetryDownload'), upload: numVal('maxRetryUpload')};
    /* Validate at the field level: report only the fields the user changed, and report them together if several are invalid. */
    var _errParts = [];
    if (maxTasks.download === null || maxTasks.download < 1 || maxTasks.download > 10) {
        _errParts.push('The maximum number of concurrent downloads must be an integer from 1 to 10');
    }
    if (maxTasks.upload === null || maxTasks.upload < 1 || maxTasks.upload > 10) {
        _errParts.push('The maximum number of concurrent uploads must be an integer from 1 to 10');
    }
    if (maxRetries.download === null || maxRetries.download < 1) {
        _errParts.push('The maximum number of download retries must be greater than 0');
    }
    if (maxRetries.upload === null || maxRetries.upload < 1) {
        _errParts.push('The maximum number of upload retries must be greater than 0');
    }
    if (_errParts.length) {
        await askAlert(_errParts.join('. ') + '.', 'Edit Settings');
        return;
    }
    /* Submit only items that actually changed: do not call endpoints for unchanged fields (so the backend will not rewrite the settings),
       and persist only once even when changing one item, avoiding logs that say "one change saved three times." */
    var dirChanged = !settingsOriginal || settingsOriginal.save_directory !== path;
    var tasksChanged = !settingsOriginal
        || settingsOriginal.max_tasks.download !== maxTasks.download
        || settingsOriginal.max_tasks.upload !== maxTasks.upload;
    var retriesChanged = !settingsOriginal
        || settingsOriginal.max_retries.download !== maxRetries.download
        || settingsOriginal.max_retries.upload !== maxRetries.upload;
    if (!dirChanged && !tasksChanged && !retriesChanged) {
        await askAlert('No changes were made.', 'Edit Settings');
        return;
    }
    try {
        /* Before submitting, compare the latest backend settings with the baseline from when the modal opened: if an item being submitted changed elsewhere,
           submitting would overwrite that change, so ask the user first; compare again before the second submission after confirmation. */
        var conflictParts = checkConfigConflict(dirChanged, tasksChanged, retriesChanged, lastSnapshot, settingsOriginal);
        if (conflictParts.length) {
            var goon = await askConfirm(
                conflictParts.join(', ') + ' changed elsewhere. Applying will overwrite those changes. Continue?', 'Edit Settings');
            if (!goon) {
                syncSettingsFromSnapshot();
                return;
            }
        }
        /* Combine multiple changes into one request: separate requests would make the backend write the settings file repeatedly, and if one fails, already-written
           items cannot be rolled back (partial application). The combined request is validated by the backend and persisted once: either all changes apply or none do.
           The three settings paths are equivalent on the backend, so use save_directory as the single entry point here. */
        var payload = {};
        if (dirChanged) {
            payload.save_directory = path;
        }
        if (tasksChanged) {
            payload.max_tasks = maxTasks;
        }
        if (retriesChanged) {
            payload.max_retries = maxRetries;
        }
        var res = await fetch('/api/config/save_directory', {
            method: 'POST',
            headers: Object.assign({'Content-Type': 'application/json'}, authHeaders()),
            body: JSON.stringify(payload)
        });
        var data = await res.json();
        /* If the save directory does not exist, the backend does not create it or persist settings; return for a second confirmation first:
           cancel leaves everything unchanged, while confirm resubmits with confirm_directory so the backend creates the directory and saves. */
        if (data.need_confirm) {
            var ok = await askConfirm(data.e_code || 'The directory does not exist. Create it?', 'Edit Settings');
            if (!ok) {
                return;
            }
            /* Settings may change elsewhere while the second confirmation is open; compare again to avoid overwriting them with stale values. */
            conflictParts = checkConfigConflict(dirChanged, tasksChanged, retriesChanged, lastSnapshot, settingsOriginal);
            if (conflictParts.length) {
                var goon2 = await askConfirm(
                    conflictParts.join(', ') + ' changed elsewhere. Applying will overwrite those changes. Continue?', 'Edit Settings');
                if (!goon2) {
                    syncSettingsFromSnapshot();
                    return;
                }
            }
            payload.confirm_directory = true;
            res = await fetch('/api/config/save_directory', {
                method: 'POST',
                headers: Object.assign({'Content-Type': 'application/json'}, authHeaders()),
                body: JSON.stringify(payload)
            });
            data = await res.json();
        }
        if (!data.status) {
            await askAlert((data.e_code || 'Failed to update settings.') + '.', 'Edit Settings');
            return;
        }
        if (dirChanged && lastSnapshot) {
            lastSnapshot.save_directory = path;
        }
        if (tasksChanged && lastSnapshot) {
            lastSnapshot.max_tasks = {download: maxTasks.download, upload: maxTasks.upload};
        }
        if (retriesChanged && lastSnapshot) {
            lastSnapshot.max_retries = {download: maxRetries.download, upload: maxRetries.upload};
        }
        /* Refresh the change-comparison baseline after saving; otherwise, clicking Apply again without closing the modal compares against stale values,
           causing duplicate submissions and writes (and repeated backend messages that the settings file was saved). */
        settingsOriginal = {
            save_directory: path,
            max_tasks: {download: maxTasks.download, upload: maxTasks.upload},
            max_retries: {download: maxRetries.download, upload: maxRetries.upload}
        };
        await askAlert('Settings have been applied.', 'Edit Settings');
    } catch (e) {
        await askAlert('Request failed: ' + e + '.', 'Edit Settings');
    }
}

function setNum(id, val) {
    var el = document.getElementById(id);
    if (el && val !== null && val !== undefined) {
        el.value = val;
    }
}

function numVal(id) {
    var raw = document.getElementById(id).value;
    if (raw === '' || raw === null) {
        return null;
    }
    var n = parseInt(raw, 10);
    return isNaN(n) ? null : n;
}

var OUTER_LINK_IDS = {github: 'linkGithub', subscribe_channel: 'linkChannel', video_tutorial: 'linkVideo', proxy_seller: 'linkProxySeller'};

function renderOuterLinks(links) {
    Object.keys(OUTER_LINK_IDS).forEach(function (key) {
        var node = document.getElementById(OUTER_LINK_IDS[key]);
        var url = (links || {})[key];
        node.href = url || '#';
        node.hidden = !url;  // Hide the menu item when the backend does not provide this link.
    });
}

function setMenuOpen(open) {
    document.getElementById('menuDropdown').hidden = !open;
}

function menuBtnClick(event) {
    event.stopPropagation();  // Stop propagation to prevent the outside-click handler from closing it immediately.
    setMenuOpen(document.getElementById('menuDropdown').hidden);
}

function menuOutsideClick(event) {
    if (!document.getElementById('menuWrap').contains(event.target)) {
        setMenuOpen(false);
    }
}

function menuEscape(event) {
    if (event.key === 'Escape') {
        setMenuOpen(false);
    }
}

function bindMenu() {
    document.getElementById('menuBtn').onclick = menuBtnClick;
    document.addEventListener('click', menuOutsideClick);
    document.addEventListener('keydown', menuEscape);
}

function isFirstLogin() {
    return document.body.getAttribute('data-first-login') === '1';  // The server sets this flag on the first login.
}

function bindSupport() {
    document.getElementById('supportBtn').onclick = openSupport;
    document.getElementById('supportClose').onclick = closeSupport;
    document.addEventListener('keydown', supportEscape);
    if (isFirstLogin()) {
        openSupport();
    }
}

var COLS_KEY = 'trmd_cols';  // Local storage key for column widths in each table.
var COLS_MIN = 48;  // Minimum width for each column to prevent dragging it too narrow to read.
var colsCache = {};  // Table name -> array of pixel widths for non-flexible columns.
var dragState = null;  // Temporary state during dragging.

function readDefaultCols(list) {
    var text = window.getComputedStyle(list).getPropertyValue('--cols');  // Custom properties can also be read from hidden elements.
    /* Remove minmax(...) from the first column first; otherwise its minimum (such as 200px in minmax(200px, 1fr))
       is also extracted as a fixed column width, adding a phantom column and making the grid tracks mismatch the header cells.
       Recalculating repeatedly while zooming would keep increasing the column count and eventually break the header. */
    text = text.replace(/minmax\([^)]*\)/g, '');
    var matches = text.match(/(\d+(?:\.\d+)?)px/g) || [];
    var widths = [];
    for (var i = 0; i < matches.length; i++) {
        widths.push(Math.round(parseFloat(matches[i])));
    }
    return widths.length ? widths : [COLS_MIN];
}

/* Position of the flexible column in --cols: it is first in regular tables; in the history table, the channel column is fixed-width and the flexible column is second.
   Split tracks as complete minmax(...) expressions so spaces inside them are not treated as separators. */
function flexIndexOf(list) {
    var text = window.getComputedStyle(list).getPropertyValue('--cols') || '';
    var tracks = text.match(/minmax\([^)]*\)|\S+/g) || [];
    for (var i = 0; i < tracks.length; i++) {
        if (tracks[i].indexOf('minmax(') === 0) {
            return i;
        }
    }
    return 0;  // Treat an undeclared flexible column as the first column, matching the original behavior.
}

/* Fixed-column index -> grid column position: indices before the flexible column stay the same; those after it shift right by one. */
function fixedGridPos(index, flexIndex) {
    return index < flexIndex ? index : index + 1;
}

var measureEl = null;  // Reuse one hidden element to measure text width instead of frequently creating nodes.

function measureTextWidth(text, cs) {
    if (!measureEl) {
        measureEl = document.createElement('span');
        measureEl.style.cssText = 'position:absolute;left:-9999px;top:0;visibility:hidden;white-space:nowrap;';
        document.body.appendChild(measureEl);
    }
    measureEl.style.fontStyle = cs.fontStyle;
    measureEl.style.fontWeight = cs.fontWeight;
    measureEl.style.fontSize = cs.fontSize;
    measureEl.style.fontFamily = cs.fontFamily;
    measureEl.style.letterSpacing = cs.letterSpacing;
    measureEl.textContent = text;
    return measureEl.offsetWidth;
}

// Measure the width each column needs to display its full header; use it as the column's minimum width.
// The returned array corresponds to the header cells; use flexIndexOf to look up the minimum for the flexible column.
function measureColMins(list) {
    var cells = list.querySelector('.list-head').children;
    var mins = [];
    for (var i = 0; i < cells.length; i++) {
        var cs = window.getComputedStyle(cells[i]);
        var need = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0) + 4;  // Padding plus a small margin so the header does not touch the edges.
        var text = cells[i].querySelector('.htext');
        if (text && text.textContent) {
            need += measureTextWidth(text.textContent, cs);
        }
        // A cell can declare an additional minimum with --col-min (for example, to keep the percentage visible in a progress column).
        var colMin = parseFloat(cs.getPropertyValue('--col-min')) || 0;
        mins.push(Math.max(COLS_MIN, Math.ceil(need), colMin));
    }
    return mins;
}

// Minimum-width safeguard for the flexible column (the name column) on mobile:
// on narrow screens, fixed columns already exceed the viewport, so the flexible column falls back to the header text width (roughly 100 pixels).
// Nested indentation then consumes part of it, making filenames almost invisible. Force a readable width on mobile,
// and let horizontal scrolling handle any overflow.
var FLEX_MIN_MOBILE = 200;

function flexColMin(measured) {
    var min = Math.max(COLS_MIN, measured || COLS_MIN);
    if (window.innerWidth <= 760) {
        min = Math.max(min, FLEX_MIN_MOBILE);
    }
    return min;
}

function applyCols(list, widths, flexMin, flexIndex) {
    if (flexIndex === undefined) {
        flexIndex = 0;  // Default to the flexible column being first, preserving existing table behavior.
    }
    var flex = 'minmax(' + (flexMin || COLS_MIN) + 'px, 1fr)';  // Keep the flexible column at least as wide as its header so other columns cannot squeeze it out of view.
    var parts = [];
    for (var i = 0; i < widths.length; i++) {
        if (i === flexIndex) {
            parts.push(flex);
        }
        parts.push(widths[i] + 'px');
    }
    if (flexIndex >= widths.length) {
        parts.push(flex);  // Append the flexible column when it is the last column.
    }
    list.style.setProperty('--cols', parts.join(' '));
}

/* Divider adjustment target: return {col: fixed-column index, sign: drag direction}.
   A regular divider adjusts the fixed column to its right: dragging right narrows it, giving space to the flexible column (sign=-1).
   If the flexible column is to the right, it has no adjustable width, so adjust the fixed column to the left instead: dragging right widens it and the flexible column absorbs the difference (sign=1). */
function gripTarget(index, flexIndex) {
    var right = index + 1;  // Grid column to the right of the divider.
    if (right === flexIndex) {
        return {col: index < flexIndex ? index : index - 1, sign: 1};
    }
    return {col: right < flexIndex ? right : right - 1, sign: -1};
}

function buildGrips(list) {
    var head = list.querySelector('.list-head');
    var cells = head.children;
    var table = list.getAttribute('data-table');
    var flexIndex = flexIndexOf(list);
    for (var i = 0; i < cells.length - 1; i++) {  // The last cell borders the container, so do not add a divider after it.
        if (cells[i].querySelector('.grip')) {
            continue;  // Do not create a divider if one already exists.
        }
        var target = gripTarget(i, flexIndex);
        var grip = document.createElement('span');
        grip.className = 'grip';
        grip.setAttribute('data-table', table);
        grip.setAttribute('data-index', target.col);
        grip.setAttribute('data-sign', target.sign);
        grip.onpointerdown = resizeStart;
        cells[i].appendChild(grip);
    }
}

function clampColsWidth(widths, index, value, maxFixed, mins, flexIndex) {
    var others = 0;
    for (var i = 0; i < widths.length; i++) {
        if (i !== index) {
            others += widths[i];
        }
    }
    // Use the width needed to show the full header as the minimum, so header titles are never compressed.
    var floor = Math.max(COLS_MIN, (mins && mins[fixedGridPos(index, flexIndex)]) || COLS_MIN);
    // Reserve the flexible column's minimum width so fixed columns cannot be dragged beyond the available space and squeeze its text.
    var flexMin = flexColMin(mins && mins[flexIndex]);
    var max;
    if (window.innerWidth <= 760) {
        // Allow horizontal scrolling on mobile instead of constraining columns to the viewport; users can drag them wider and scroll to see overflow.
        max = Math.max(value, 900);
    } else {
        max = Math.max(COLS_MIN, maxFixed - others - flexMin);
    }
    // Prioritize headers: preserve the width needed for titles when space is limited, allowing rows to overflow rather than compressing header text.
    return Math.max(floor, Math.min(value, max));
}

function resizeStart(event) {
    var grip = event.currentTarget;
    var list = grip.closest('.list');
    var head = list.querySelector('.list-head');
    var index = Number(grip.getAttribute('data-index'));
    var table = list.getAttribute('data-table');
    var widths = colsCache[table] || readDefaultCols(list);
    var style = window.getComputedStyle(head);
    var gap = parseFloat(style.columnGap) || 0;
    var padding = (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0);
    dragState = {
        list: list,
        table: table,
        index: index,
        col: index,  // Each divider is the left edge of the fixed column to its right; always adjust that column so each column has exactly one divider.
        sign: Number(grip.getAttribute('data-sign')) || -1,  // Drag direction when moving right; the divider sets this to reverse when the flexible column is on the right.
        flexIndex: flexIndexOf(list),  // Position of the flexible column, used to map widths and minimums.
        origin: widths.slice(),
        widths: widths.slice(),
        startX: event.clientX,
        maxFixed: Math.max(head.clientWidth - padding - gap * widths.length, 0),
        mins: measureColMins(list)  // Minimum widths required by each column header; keep them constant while dragging.
    };
    event.preventDefault();
    event.stopPropagation();
    document.body.classList.add('resizing');
    document.addEventListener('pointermove', resizeMove);
    document.addEventListener('pointerup', resizeEnd);
}

function resizeMove(event) {
    if (!dragState) {
        return;
    }
    var delta = event.clientX - dragState.startX;
    var value = dragState.origin[dragState.col] + delta * dragState.sign;
    dragState.widths[dragState.col] = clampColsWidth(dragState.widths, dragState.col, value, dragState.maxFixed, dragState.mins, dragState.flexIndex);
    applyCols(dragState.list, dragState.widths, flexColMin(dragState.mins[dragState.flexIndex]), dragState.flexIndex);
    event.preventDefault();
}

function resizeEnd() {
    if (!dragState) {
        return;
    }
    colsCache[dragState.table] = dragState.widths;
    try {
        localStorage.setItem(COLS_KEY, JSON.stringify(colsCache));  // Remember these column widths and restore them after refresh.
    } catch (e) {
        // Ignore write failures in private browsing mode.
    }
    document.body.classList.remove('resizing');
    document.removeEventListener('pointermove', resizeMove);
    document.removeEventListener('pointerup', resizeEnd);
    dragState = null;
}

function initCols() {
    try {
        colsCache = JSON.parse(localStorage.getItem(COLS_KEY) || '{}') || {};
    } catch (e) {
        colsCache = {};
    }
    var lists = document.querySelectorAll('.list[data-table]');
    for (var i = 0; i < lists.length; i++) {
        var list = lists[i];
        var table = list.getAttribute('data-table');
        var head = list.querySelector('.list-head');
        var flexIndex = flexIndexOf(list);  // Flexible-column position: first in regular tables, second in the history table.
        var widths = colsCache[table];
        if (!widths || widths.length !== head.children.length - 1) {
            widths = readDefaultCols(list);  // Fall back to default column widths when the column count changes or on first load.
        }
        var mins = measureColMins(list);
        var j;
        for (j = 0; j < widths.length; j++) {
            widths[j] = Math.max(widths[j], mins[fixedGridPos(j, flexIndex)]);  // Saved column widths must also be at least as wide as their headers require.
        }
        colsCache[table] = widths;
        applyCols(list, widths, flexColMin(mins[flexIndex]), flexIndex);
        buildGrips(list);
    }
}

// Reapply column widths across breakpoints (screen rotation or window resizing),
// so the mobile minimum width for the flexible column is correctly applied or removed when entering or leaving a narrow layout.
/* Zooming and window resizing both change innerWidth (CSS pixels).
   Debounce and recalculate widths in one place to prevent stale widths at high zoom levels from breaking the header. */
var resizeTimer = null;
window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(initCols, 150);
});

var savedSection = '';
var savedListen = '';
var savedNotice = '';
var savedStorage = '';
try {
    savedSection = localStorage.getItem(SECTION_KEY) || '';
    savedListen = localStorage.getItem(LISTEN_KEY) || '';
    savedNotice = localStorage.getItem(NOTICE_KEY) || '';
    savedStorage = localStorage.getItem(STORAGE_KEY) || '';
    collapsed = JSON.parse(localStorage.getItem(COLLAPSE_KEY) || '{}') || {};  // Restore each group's collapsed state.
    allCollapsed = localStorage.getItem(ALL_KEY) === '1';
    uploadAllCollapsed = localStorage.getItem(UPLOAD_ALL_KEY) === '1';
    lastLinkCollapsed = localStorage.getItem(LINK_LAST_KEY) !== '0';  // Keep the link level collapsed by default when no value is stored.
    lastUploadCollapsed = localStorage.getItem(UPLOAD_LAST_KEY) === '1';  // Keep the upload channel level expanded by default when no value is stored.
} catch (e) {
    savedSection = '';
    savedListen = '';
    savedStorage = '';
    collapsed = {};
    allCollapsed = false;
    uploadAllCollapsed = false;
    lastLinkCollapsed = true;
    lastUploadCollapsed = false;
}

function initVersion() {
    var tip = document.getElementById('logoVersion');
    var trmd = document.getElementById('tipTrmd');
    var pyrogram = document.getElementById('tipPyrogram');
    if (trmd.textContent.indexOf('__') === 0 || pyrogram.textContent.indexOf('__') === 0) {
        tip.hidden = true;  // Hide the tip if the server has not replaced the placeholder, so raw placeholder text is not shown.
    }
}

/* Handle native title tooltips consistently: use the custom glass tooltip for every element with a title,
   avoiding a mix of browser-default and custom styles (untruncated names would otherwise show a native tooltip). */
var nameTipEl = null;
var nameTipFor = null;
var tipMouseX = 0;
var tipMouseY = 0;

function nameTipNode() {
    if (!nameTipEl) {
        nameTipEl = document.getElementById('nameTip');
    }
    return nameTipEl;
}

// Get the nearest element with tooltip text (data-tip or title).
function nameTipTarget(node) {
    if (!node || !node.closest) {
        return null;
    }
    return node.closest('[data-tip], [title]');
}

// Native title and custom tooltips would appear together, so on first encounter move the text to data-tip and remove title.
function takeTipText(el) {
    if (el.hasAttribute('title')) {
        el.setAttribute('data-tip', el.getAttribute('title'));
        el.removeAttribute('title');
    }
    return el.getAttribute('data-tip') || '';
}

function showNameTip(el) {
    var text = takeTipText(el);
    var tip = nameTipNode();
    if (!text || !tip) {
        return;
    }
    tip.textContent = text;
    tip.classList.add('show');  // Show it first to measure its actual size, then position it.
    var rect = el.getBoundingClientRect();
    var left = rect.left;
    var top = rect.bottom + 8;
    var width = tip.offsetWidth;
    var height = tip.offsetHeight;
    if (left + width > window.innerWidth - 8) {
        left = Math.max(8, window.innerWidth - width - 8);
    }
    if (top + height > window.innerHeight - 8) {
        top = Math.max(8, rect.top - height - 8);  // Move it above the element if there is not enough room below.
    }
    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
    nameTipFor = el;
}

function hideNameTip() {
    if (nameTipEl) {
        nameTipEl.classList.remove('show');
    }
    nameTipFor = null;
}

// The list redraws every second and destroys the hovered element; reposition the tooltip after redraw based on the current mouse location.
function refreshNameTip() {
    if (!nameTipFor || nameTipFor.isConnected) {
        return;
    }
    var el = nameTipTarget(document.elementFromPoint(tipMouseX, tipMouseY));
    if (el) {
        showNameTip(el);
    } else {
        hideNameTip();
    }
}

function initNameTip() {
    document.addEventListener('mousemove', function (event) {
        tipMouseX = event.clientX;
        tipMouseY = event.clientY;
    });
    document.addEventListener('mouseover', function (event) {
        if (document.body.classList.contains('resizing')) {
            return;  // Do not show a tooltip while dragging column widths, to avoid interference.
        }
        if (nameTipFor && !nameTipFor.isConnected) {
            hideNameTip();
        }
        var el = nameTipTarget(event.target);
        if (!el || nameTipFor === el) {
            return;
        }
        showNameTip(el);
    });
    document.addEventListener('mouseout', function (event) {
        var el = nameTipTarget(event.target);
        var to = nameTipTarget(event.relatedTarget);
        if (el && nameTipFor === el && to !== el) {
            hideNameTip();  // Do not hide while moving within the same element, to avoid flicker.
        }
    });
    window.addEventListener('scroll', hideNameTip, true);  // Scrolling invalidates the position, so hide it.
    document.addEventListener('pointerdown', function (event) {
        if (nameTipTarget(event.target) !== nameTipFor) {
            hideNameTip();  // Close it when clicking outside the tooltip.
        }
    });
}

/*
 * ===== Gradient background implementation =====
 * Ported from util/gradientBackground.ts in telegram-tt (web.telegram.org/a);
 * the gradient algorithm was adapted from http://useless.altervista.org/gradient.html (original script author unknown).
 * The original code is licensed under GNU GPL-3.0; copyright belongs to the respective original authors.
 * Ported and modified by: Gentlesprite, 2026-09
 * Changes: rewrote the original React/TS implementation in native JS and adapted it to this project's DOM structure.
 * SPDX-License-Identifier: GPL-3.0-only
 */
/* ===== Gradient background, ported line by line from the official util/gradientBackground.ts in web.telegram.org/a (telegram-tt) =====
   Note: the official Web A and Web K (tweb) gradients are different implementations, with different point coordinates, blending formulas, and color order. */
var BG_GRADIENT_SIZE = 100;  // Official useGradientBackground CANVAS_SIZE = 100; CSS stretches it for a softer appearance.
var BG_GRADIENT_SPEED = 0.1;  // Official ANIMATION_SPEED: per-frame interpolation factor for moving color points toward their targets.
var BG_GRADIENT_EPSILON = 0.01;  // Official POSITION_EPSILON: a point is considered to have arrived when its distance to the target is below this value.
var BG_GRADIENT_BLEND_POWER = 3;  // Official BLEND_POWER: exponent used to weight the difference in distance from the nearest color point.
var BG_GRADIENT_STEP = 2;  // Official KEY_POINT_STEP: each color point advances by 2 indices at a time.
var BG_GRADIENT_POINTS = [  // Official KEY_POINTS: normalized coordinates of 8 color points.
    [0.265, 0.582],
    [0.176, 0.918],
    [0.415, 0.836],
    [0.644, 0.755],
    [0.735, 0.418],
    [0.824, 0.082],
    [0.585, 0.164],
    [0.356, 0.245]
];
var bgCanvas = null;
var bgCtx = null;
var bgHelperCanvas = null;  // Hidden small canvas; write ImageData here before copying it to the main canvas, matching the official two-level structure.
var bgHelperCtx = null;
var bgColors = [];
var bgKeyShift = 0;
var bgCurrentPositions = [];
var bgTargetPositions = [];
var bgAnimating = false;
var bgLastProgress = -1;  // Total number of completed tasks in the previous check; -1 means the baseline has not yet been recorded.
// Doodle-mask baking: rasterize pattern.svg, then bake it into the canvas each frame with destination-in instead of CSS mask-image,
// eliminating Chrome's tiled flicker when redrawing a masked canvas each frame (this bug does not occur in Edge).
var bgDoodleImg = null;     // Loaded doodle source image with dimensions filled in.
var bgDoodlePattern = null; // Repeating pattern generated from the mask tile canvas, tiled 1:1 in device-pixel space.
var bgDoodleLoader = null;  // Mask image loader.
var bgDoodleDpr = 0;        // Pixel density used for the current tile, to determine whether it needs rebuilding.
var bgDoodleTileW = 0;      // Mask tile width in device pixels, corresponding to the official mask-size of 26.875rem (430px).
var bgDoodleTileH = 0;      // Mask tile height in device pixels, calculated from the source image's aspect ratio.
var bgDoodleOffX = 0;       // Horizontal offset of the repeating origin for the official mask-position:center (device pixels).
var bgDoodleOffY = 0;       // Vertical offset of the repeating origin for the official mask-position:center (device pixels).
var BG_PATTERN_URL = 'img/pattern.svg';     // Official doodle pattern, the same file as the removed CSS mask-image.
var BG_PATTERN_TILE = 430;                   // Tile width in CSS pixels corresponding to the official 26.875rem (1rem = 16px).
var BG_PATTERN_ASPECT = 2960 / 1440;         // Aspect ratio of the mask source viewBox, used as a fallback if intrinsic dimensions are unavailable.

function bgHexToRgb(hex) {  // Parse an #rrggbb color into an [r, g, b] array.
    var value = parseInt(hex.slice(1, 7), 16);
    return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

function bgGetPositions(shift) {  // Official buildTargetPositions: select 4 points using keyPoints[(shift + i × 2) % 8].
    var result = [];
    for (var i = 0; i < 4; i++) {
        var point = BG_GRADIENT_POINTS[(shift + i * BG_GRADIENT_STEP) % BG_GRADIENT_POINTS.length];
        result.push([point[0], point[1]]);
    }
    return result;
}

var bgImageData = null;  // Reused ImageData; creating one every frame would cause significant GC pressure.

function bgGetGradientImageData() {  // Official drawStaticGradient: blend four colors using the cube of the distance difference from the nearest color point.
    // Optimizations: reuse ImageData, avoid per-pixel array allocations, and replace Math.pow with multiplication; the visual result is identical.
    if (!bgImageData) {
        bgImageData = bgHelperCtx.createImageData(BG_GRADIENT_SIZE, BG_GRADIENT_SIZE);
    }
    var pixels = bgImageData.data;
    var offset = 0;
    var size = BG_GRADIENT_SIZE;
    // Move color-point coordinates and colors outside the loop to avoid repeated array reads for every pixel.
    var px0 = bgCurrentPositions[0][0], py0 = bgCurrentPositions[0][1];
    var px1 = bgCurrentPositions[1][0], py1 = bgCurrentPositions[1][1];
    var px2 = bgCurrentPositions[2][0], py2 = bgCurrentPositions[2][1];
    var px3 = bgCurrentPositions[3][0], py3 = bgCurrentPositions[3][1];
    var c0r = bgColors[0][0], c0g = bgColors[0][1], c0b = bgColors[0][2];
    var c1r = bgColors[1][0], c1g = bgColors[1][1], c1b = bgColors[1][2];
    var c2r = bgColors[2][0], c2g = bgColors[2][1], c2b = bgColors[2][2];
    var c3r = bgColors[3][0], c3g = bgColors[3][1], c3b = bgColors[3][2];
    for (var y = 0; y < size; y++) {
        var yRatio = y / size;
        // Calculate the row-direction difference once in the outer loop and reuse it in the inner loop.
        var ay = yRatio - py0, by = yRatio - py1, cy = yRatio - py2, dy = yRatio - py3;
        var ay2 = ay * ay, by2 = by * by, cy2 = cy * cy, dy2 = dy * dy;
        for (var x = 0; x < size; x++) {
            var xRatio = x / size;
            var ax = xRatio - px0, bx = xRatio - px1, cx = xRatio - px2, dx = xRatio - px3;
            var d0 = Math.sqrt(ax * ax + ay2);
            var d1 = Math.sqrt(bx * bx + by2);
            var d2 = Math.sqrt(cx * cx + cy2);
            var d3 = Math.sqrt(dx * dx + dy2);
            var min = d0;
            if (d1 < min) {
                min = d1;
            }
            if (d2 < min) {
                min = d2;
            }
            if (d3 < min) {
                min = d3;
            }
            // Weight = (1 - (distance - nearest distance)) raised to BG_GRADIENT_BLEND_POWER (3);
            // Replace Math.pow with repeated multiplication for the constant exponent 3, which is an order of magnitude faster.
            var k0 = 1 - (d0 - min), k1 = 1 - (d1 - min);
            var k2 = 1 - (d2 - min), k3 = 1 - (d3 - min);
            var w0 = k0 * k0 * k0, w1 = k1 * k1 * k1;
            var w2 = k2 * k2 * k2, w3 = k3 * k3 * k3;
            var total = w0 + w1 + w2 + w3;
            if (total < 0) {
                total = -total;
            }
            if (total === 0) {
                total = 1;
            }  // Avoid division by zero (the original implementation would produce NaN).
            var n0 = w0 / total, n1 = w1 / total, n2 = w2 / total, n3 = w3 / total;
            pixels[offset++] = c0r * n0 + c1r * n1 + c2r * n2 + c3r * n3;
            pixels[offset++] = c0g * n0 + c1g * n1 + c2g * n2 + c3g * n3;
            pixels[offset++] = c0b * n0 + c1b * n1 + c2b * n2 + c3b * n3;
            pixels[offset++] = 255;
        }
    }
    return bgImageData;
}

function bgDrawImageData(id) {  // Write to the hidden canvas first, stretch-copy to the device-resolution main canvas, then bake in the doodle with destination-in.
    var viewW = bgCanvas.width || BG_GRADIENT_SIZE;
    var viewH = bgCanvas.height || BG_GRADIENT_SIZE;
    bgHelperCtx.putImageData(id, 0, 0);
    bgCtx.save();
    bgCtx.globalCompositeOperation = 'source-over';
    bgCtx.clearRect(0, 0, viewW, viewH);
    bgCtx.imageSmoothingEnabled = true;
    bgCtx.drawImage(bgHelperCanvas, 0, 0, BG_GRADIENT_SIZE, BG_GRADIENT_SIZE, 0, 0, viewW, viewH);
    if (bgDoodlePattern) {
        /* Bake the doodle into the canvas pixels with destination-in instead of CSS mask-image, so the browser no longer handles the mask in a compositing layer.
           Each frame now needs only two full-screen draws, eliminating Chrome's tiled flicker from recompositing the mask every frame.
           Tile the pattern 1:1 in device-pixel space without scaling, preserving the sharpness of the vector mask. */
        bgCtx.globalCompositeOperation = 'destination-in';
        bgCtx.setTransform(1, 0, 0, 1, 0, 0);
        bgCtx.translate(bgDoodleOffX, bgDoodleOffY);
        bgCtx.fillStyle = bgDoodlePattern;
        bgCtx.fillRect(-bgDoodleOffX, -bgDoodleOffY, viewW, viewH);
    }
    bgCtx.restore();
}

function bgDoodleAspect() {  // Aspect ratio of the mask source: prefer intrinsic dimensions, falling back to the viewBox for cases such as the default 300×150 size.
    var width = bgDoodleImg.naturalWidth;
    var height = bgDoodleImg.naturalHeight;
    if (width > 0 && height > 0) {
        var ratio = height / width;
        if (ratio > 1.2 && ratio < 3.0) {  // Accept a plausible doodle aspect ratio and exclude the browser's fallback 300×150 dimensions.
            return ratio;
        }
    }
    return BG_PATTERN_ASPECT;
}

function bgBuildDoodle() {  // Rasterize the mask source into a tile canvas at the current device pixel ratio, then create the repeating pattern.
    if (!bgDoodleImg || !bgCtx) {
        return;
    }
    var dpr = window.devicePixelRatio || 1;  // Do not cap the value: the browser DPR rises when zooming, and rasterizing at the real value keeps it sharp at 1:1.
    if (bgDoodlePattern && bgDoodleDpr === dpr) {
        return;  // No rebuild is needed if the pixel density is unchanged; this avoids repeatedly rasterizing the SVG while resizing the window.
    }
    bgDoodleDpr = dpr;
    var tileW = Math.max(1, Math.round(BG_PATTERN_TILE * dpr));
    var tileH = Math.max(1, Math.round(BG_PATTERN_TILE * bgDoodleAspect() * dpr));
    var tile = document.createElement('canvas');
    tile.width = tileW;
    tile.height = tileH;
    var tileCtx = tile.getContext('2d');
    // Match the tile aspect ratio to the viewBox; rasterizing the SVG vector at the target size prevents blur and empty margins.
    tileCtx.drawImage(bgDoodleImg, 0, 0, tileW, tileH);
    bgDoodlePattern = bgCtx.createPattern(tile, 'repeat');
}

function bgUpdateDoodleGeometry() {  // Calculate centered tile offsets in device pixels from the tile aspect ratio and canvas dimensions.
    if (!bgDoodleImg || !bgCanvas) {
        return;
    }
    var dpr = window.devicePixelRatio || 1;  // Do not cap the value: keep it consistent with tile rasterization and canvas resolution for sharp zooming.
    bgDoodleTileW = BG_PATTERN_TILE * dpr;
    bgDoodleTileH = bgDoodleTileW * bgDoodleAspect();
    bgDoodleOffX = ((bgCanvas.width - bgDoodleTileW) / 2) % bgDoodleTileW;
    bgDoodleOffY = ((bgCanvas.height - bgDoodleTileH) / 2) % bgDoodleTileH;
}

function bgResizeCanvas() {  // Set the main canvas to the viewport's device resolution, sync the mask tile offsets and pattern, then redraw immediately.
    if (!bgCanvas || !bgCtx) {
        return;
    }
    var dpr = window.devicePixelRatio || 1;  // Do not cap the value: build the canvas at the actual device resolution so it stays sharp when zoomed and resized.
    var width = Math.max(1, Math.round((bgCanvas.clientWidth || window.innerWidth || 1) * dpr));
    var height = Math.max(1, Math.round((bgCanvas.clientHeight || window.innerHeight || 1) * dpr));
    if (bgCanvas.width !== width || bgCanvas.height !== height) {
        bgCanvas.width = width;  // Changing the dimensions clears the canvas and resets its state, so rebuild the transform.
        bgCanvas.height = height;
    }
    bgUpdateDoodleGeometry();
    bgBuildDoodle();
    bgDrawImageData(bgGetGradientImageData());
}

function bgEnsureSvgSize(text) {  // Add width/height matching the viewBox to an SVG without intrinsic dimensions, preventing blur from scaling.
    return text.replace(/<svg([^>]*)>/i, function (match, attrs) {
        if (/\bwidth\s*=/.test(attrs) && /\bheight\s*=/.test(attrs)) {
            return match;
        }
        var box = attrs.match(/viewBox\s*=\s*["']\s*[\d.]+\s+[\d.]+\s+([\d.]+)\s+([\d.]+)/i);
        if (!box) {
            return match;
        }
        return '<svg' + attrs + ' width="' + box[1] + '" height="' + box[2] + '">';
    });
}

function bgLoadDoodle() {  // Load the doodle mask asynchronously, bake it into the canvas and show the background when ready, or fall back to a plain gradient on failure.
    bgDoodleLoader = new Image();
    bgDoodleLoader.onload = function () {
        bgDoodleImg = bgDoodleLoader;
        bgUpdateDoodleGeometry();
        bgBuildDoodle();
        bgDrawImageData(bgGetGradientImageData());
        bgCanvas.classList.add('on');
        if (bgDoodleLoader.src.indexOf('blob:') === 0) {
            URL.revokeObjectURL(bgDoodleLoader.src);
        }
    };
    bgDoodleLoader.onerror = function () {  // If the mask fails to load, fall back to a plain gradient background without doodles, at least avoiding flicker.
        bgCanvas.classList.add('on');
    };
    // Loading an SVG without intrinsic dimensions directly makes the browser fall back to 300×150 and then enlarge it, blurring the doodles;
    // fetch the text first, add width/height matching the viewBox, then create a Blob URL so it rasterizes sharply at the target size.
    if (typeof fetch === 'function') {
        fetch(BG_PATTERN_URL).then(function (response) {
            return response.text();
        }).then(function (text) {
            var blob = new Blob([bgEnsureSvgSize(text)], {type: 'image/svg+xml'});
            bgDoodleLoader.src = URL.createObjectURL(blob);
        }).catch(function () {
            bgDoodleLoader.src = BG_PATTERN_URL;  // If fetching the text fails, fall back to direct loading (which may be blurry).
        });
    } else {
        bgDoodleLoader.src = BG_PATTERN_URL;
    }
}

function bgStepPositions() {  // Official stepPositions: linearly interpolate color points toward their targets by 0.1, stopping when they arrive.
    var moving = false;
    for (var i = 0; i < 4; i++) {
        var current = bgCurrentPositions[i];
        var target = bgTargetPositions[i];
        if (Math.abs(current[0] - target[0]) > BG_GRADIENT_EPSILON
            || Math.abs(current[1] - target[1]) > BG_GRADIENT_EPSILON) {
            moving = true;
        }
        current[0] = current[0] * (1 - BG_GRADIENT_SPEED) + target[0] * BG_GRADIENT_SPEED;
        current[1] = current[1] * (1 - BG_GRADIENT_SPEED) + target[1] * BG_GRADIENT_SPEED;
    }
    return moving;
}

function bgAnimate() {  // Official animate: redraw each frame only while color points are moving, then stop automatically with almost no overhead.
    var moving = bgStepPositions();
    bgDrawImageData(bgGetGradientImageData());
    if (moving) {
        requestAnimationFrame(bgAnimate);
    } else {
        bgAnimating = false;
    }
}

function bgAdvancePosition() {  // Official advancePosition: move to the next target and start interpolation; the official code calls this when sending a message.
    bgTargetPositions = bgGetPositions(bgKeyShift);
    bgKeyShift = (bgKeyShift + 1) % BG_GRADIENT_POINTS.length;
    if (!bgAnimating) {
        bgAnimating = true;
        requestAnimationFrame(bgAnimate);
    }
}

function initBackgroundGradient() {
    bgCanvas = document.getElementById('bgGradient');
    if (!bgCanvas || !bgCanvas.getContext) {
        return;
    }
    bgHelperCanvas = document.createElement('canvas');
    bgHelperCanvas.width = BG_GRADIENT_SIZE;
    bgHelperCanvas.height = BG_GRADIENT_SIZE;
    bgHelperCtx = bgHelperCanvas.getContext('2d', {alpha: false});
    var colors = (bgCanvas.getAttribute('data-colors') || '').split(',');
    for (var i = 0; i < colors.length; i++) {
        var color = colors[i].trim();
        if (/^#[0-9a-fA-F]{6}$/.test(color)) {
            bgColors.push(bgHexToRgb(color));
        }
    }
    if (!bgColors.length) {
        return;
    }
    // The official initial points are keyPoints[0,2,4,6]; the first targets match their current positions, so after loading the page is in the same static state as the official version.
    bgCurrentPositions = bgGetPositions(0);
    bgTargetPositions = bgGetPositions(0);
    bgKeyShift = 1;
    // Enable alpha so areas outside the doodles are transparent and reveal the page background, matching the original CSS mask appearance.
    bgCtx = bgCanvas.getContext('2d', {alpha: true});
    bgResizeCanvas();  // Build the main canvas at device resolution and draw the first frame (gradient only; no doodles yet).
    window.addEventListener('resize', bgResizeCanvas);
    bgLoadDoodle();  // Add the on class only after the mask is ready, preventing an unmasked full-screen gradient from flashing.
}

bindSections();
bindListenTabs();
bindNoticeTabs();
bindStorageTabs();
bindStorageHover();
bindStoragePager();
bindStorageFilters();
bindListenRemove();
bindConfirm();
bindLogin();
initLogout();
bindStatFilter();
bindSupport();
bindMenu();
initSettings();
initVersion();
loadStorageFilters();  // Restore filters first so the header rebuilt below can show the active funnel state.
currentStorage = STORAGE_TABS.indexOf(savedStorage) > -1 ? savedStorage : 'download';
applyStorageTab();  // Update the highlight from the saved selection first; data has not been fetched yet, so the list remains empty.
applySectionVisibility();  // Adjust the sidebar to available features; switchSection will then lock to an available page.
switchSection(savedSection);
switchListen(savedListen);
currentNotice = NOTICE_TABS.indexOf(savedNotice) > -1 ? savedNotice : 'download';
applyNoticeTab();  // Update the highlight from the saved selection first; data has not been fetched yet, so the list remains empty.
document.getElementById('toggleAll').onclick = toggleAll;
document.getElementById('toggleUpload').onclick = toggleUploadAll;
initCols();  // Restore the previous column widths and create the draggable dividers.
bindPause();  // Bind the global pause/resume button.
initNameTip();  // Show the full filename on hover.
initBackgroundGradient();  // Start the Telegram-style animated gradient background.

/* Pause polling when the page is not visible (switched to a background tab or minimized).
   A background tab is not composited for display, so continuing to fetch data, compare fingerprints, and rebuild the DOM every second only wastes CPU;
   refresh immediately when it returns to the foreground, with no visible impact. */
var pollTimer = 0;

function startPolling() {
    if (!pollTimer) {
        pollTimer = setInterval(refresh, POLL_INTERVAL_MS);
    }
}

function stopPolling() {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = 0;
    }
}

document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
        stopPolling();
    } else {
        refresh();  // Refresh immediately on return to the foreground to avoid showing stale data from the background interval.
        startPolling();
    }
});

refresh(true);  // Force the initial page to render with the latest data, skipping deduplication so progress bars display correctly from the start.
startPolling();
startStoragePolling();  // History-page polling checks the current section internally and queries the database only while the history page is active.
