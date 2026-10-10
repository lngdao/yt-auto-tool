# YouTube Batch Link Picker

Adds a checkbox to videos on YouTube channel pages and a floating bottom-right panel that copies selected links or titles, one item per line. Videos copied from the selection are labeled with the date they were last picked.

## Install in Chrome or Edge

1. Open chrome://extensions in Chrome or edge://extensions in Edge.
2. Turn on Developer mode.
3. Choose Load unpacked and select this youtube-link-picker folder.
4. Reload any YouTube channel tab that was already open.

## Use

1. Open a channel page, such as youtube.com/@channel/videos.
2. Check videos individually, or click Select visible to check cards currently loaded on the page.
3. Click Copy links to copy the selected URLs and mark those videos as picked. Their date labels are saved locally and restored when you reopen the browser. Copy titles only copies titles. Labels do not prevent selecting a video again.
4. Paste the copied URLs into YouTube Video Batch Tool.
5. Clear resets the current selection. Selection stays while navigating between YouTube pages inside the same tab.

The extension supports channel handles and legacy /channel/, /c/, and /user/ URLs. It only reads links from the open YouTube page; it does not contact a server or download video data.

The clipboardWrite permission is used only when you click Copy links or Copy titles. The storage permission keeps picked-video labels in this browser profile; this data is not sent to a server.
