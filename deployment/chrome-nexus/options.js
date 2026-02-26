// Options page script
document.addEventListener('DOMContentLoaded', async () => {
  const result = await chrome.storage.sync.get({
    nexusUrl: 'http://localhost:8700/api',
    defaultCategory: 'research',
    autoTags: 'web-capture',
    autoIngestYoutube: true
  });

  document.getElementById('nexusUrl').value = result.nexusUrl;
  document.getElementById('defaultCategory').value = result.defaultCategory;
  document.getElementById('autoTags').value = result.autoTags;
  document.getElementById('autoIngestYoutube').checked = result.autoIngestYoutube;
});

document.getElementById('save').addEventListener('click', async () => {
  await chrome.storage.sync.set({
    nexusUrl: document.getElementById('nexusUrl').value,
    defaultCategory: document.getElementById('defaultCategory').value,
    autoTags: document.getElementById('autoTags').value,
    autoIngestYoutube: document.getElementById('autoIngestYoutube').checked
  });
  showStatus('Settings saved!', 'success');
});

document.getElementById('test').addEventListener('click', async () => {
  const url = document.getElementById('nexusUrl').value;
  try {
    const response = await fetch(`${url}/health`);
    if (response.ok) {
      showStatus('Connected to Nexus successfully!', 'success');
    } else {
      showStatus(`Nexus responded with status ${response.status}`, 'error');
    }
  } catch (error) {
    showStatus(`Cannot reach Nexus at ${url}`, 'error');
  }
});

function showStatus(message, type) {
  const el = document.getElementById('status');
  el.textContent = message;
  el.className = `status ${type}`;
  setTimeout(() => { el.style.display = 'none'; }, 3000);
}
