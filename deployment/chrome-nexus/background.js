// Send to Nexus — Chrome Extension Background Service Worker

const DEFAULT_NEXUS_URL = 'http://localhost:8700/api';
const YOUTUBE_REGEX = /^https?:\/\/(www\.)?(youtube\.com\/watch|youtu\.be\/)/;

// Create context menus on install
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: 'send-link-to-nexus',
    title: 'Send Link to Nexus',
    contexts: ['link']
  });

  chrome.contextMenus.create({
    id: 'send-page-to-nexus',
    title: 'Send This Page to Nexus',
    contexts: ['page']
  });

  chrome.contextMenus.create({
    id: 'send-selection-to-nexus',
    title: 'Send Selection to Nexus',
    contexts: ['selection']
  });
});

// Handle context menu clicks
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const config = await getConfig();

  switch (info.menuItemId) {
    case 'send-link-to-nexus':
      await sendToNexus(info.linkUrl, 'link', config, tab);
      break;
    case 'send-page-to-nexus':
      await sendToNexus(tab.url, 'page', config, tab, tab.title);
      break;
    case 'send-selection-to-nexus':
      await sendToNexus(info.selectionText, 'text', config, tab);
      break;
  }
});

async function getConfig() {
  const result = await chrome.storage.sync.get({
    nexusUrl: DEFAULT_NEXUS_URL,
    defaultCategory: 'research',
    autoTags: 'web-capture',
    autoIngestYoutube: true
  });
  return result;
}

async function sendToNexus(content, type, config, tab, title) {
  const nexusUrl = config.nexusUrl;

  try {
    // Check if it's a YouTube URL
    if (type === 'link' && YOUTUBE_REGEX.test(content) && config.autoIngestYoutube) {
      await sendYouTubeToNexus(content, config);
      return;
    }

    // Build entry
    const entry = {
      title: title || buildTitle(content, type),
      content: buildContent(content, type, tab),
      content_type: type === 'text' ? 'note' : 'document',
      category: config.defaultCategory,
      tags: config.autoTags.split(',').map(t => t.trim()).filter(Boolean)
    };

    const response = await fetch(`${nexusUrl}/entries`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(entry)
    });

    if (response.ok) {
      showNotification('Sent to Nexus', `"${entry.title}" saved successfully`);
    } else {
      const err = await response.text();
      showNotification('Nexus Error', `Failed: ${err.substring(0, 100)}`);
    }
  } catch (error) {
    showNotification('Nexus Unreachable', `Cannot connect to ${nexusUrl}`);
  }
}

async function sendYouTubeToNexus(url, config) {
  try {
    const response = await fetch(`${config.nexusUrl}/youtube/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: url,
        category: config.defaultCategory
      })
    });

    if (response.ok) {
      showNotification('YouTube → Nexus', `Video imported successfully`);
    } else {
      // Fallback: store as a regular link
      const entry = {
        title: `YouTube: ${url}`,
        content: `YouTube video URL: ${url}\n\nQueued for manual transcript import.`,
        content_type: 'document',
        category: config.defaultCategory,
        tags: ['youtube', 'web-capture']
      };
      await fetch(`${config.nexusUrl}/entries`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(entry)
      });
      showNotification('YouTube → Nexus', 'Saved as link (auto-import unavailable)');
    }
  } catch (error) {
    showNotification('Nexus Error', `YouTube import failed: ${error.message}`);
  }
}

function buildTitle(content, type) {
  if (type === 'link') {
    try {
      const url = new URL(content);
      return `Web: ${url.hostname}${url.pathname.substring(0, 50)}`;
    } catch {
      return `Link: ${content.substring(0, 60)}`;
    }
  }
  if (type === 'text') {
    return `Note: ${content.substring(0, 60)}...`;
  }
  return `Capture: ${content.substring(0, 60)}`;
}

function buildContent(content, type, tab) {
  const timestamp = new Date().toISOString();
  if (type === 'link') {
    return `## Web Capture\n\n**URL:** ${content}\n**Source Page:** ${tab?.url || 'unknown'}\n**Captured:** ${timestamp}\n`;
  }
  if (type === 'text') {
    return `## Text Selection\n\n${content}\n\n**Source:** ${tab?.url || 'unknown'}\n**Captured:** ${timestamp}\n`;
  }
  return `## Page Capture\n\n**URL:** ${content}\n**Title:** ${tab?.title || 'unknown'}\n**Captured:** ${timestamp}\n`;
}

function showNotification(title, message) {
  chrome.notifications.create({
    type: 'basic',
    iconUrl: 'icons/icon48.png',
    title: title,
    message: message
  });
}
