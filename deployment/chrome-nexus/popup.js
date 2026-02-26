document.addEventListener('DOMContentLoaded', async () => {
  const { nexusUrl } = await chrome.storage.sync.get({ nexusUrl: 'http://localhost:8700/api' });
  const statusEl = document.getElementById('status');
  const statsEl = document.getElementById('stats');

  try {
    const r = await fetch(`${nexusUrl}/health`, { signal: AbortSignal.timeout(3000) });
    if (r.ok) {
      statusEl.textContent = '● Connected to Nexus';
      statusEl.className = 'status ok';
      try {
        const sr = await fetch(`${nexusUrl}/stats`, { signal: AbortSignal.timeout(3000) });
        if (sr.ok) {
          const stats = await sr.json();
          statsEl.innerHTML = `
            <div class="stat">Entries: ${stats.total_entries || '?'}</div>
            <div class="stat">Q&A Pairs: ${stats.total_qa || '?'}</div>
          `;
        }
      } catch { /* stats endpoint optional */ }
    } else {
      statusEl.textContent = `● Nexus error (${r.status})`;
      statusEl.className = 'status err';
    }
  } catch {
    statusEl.textContent = '● Nexus unreachable';
    statusEl.className = 'status err';
  }

  document.getElementById('sendPage').addEventListener('click', async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) {
      const entry = {
        title: `Web: ${tab.title || tab.url}`,
        content: `## Page Capture\n\n**URL:** ${tab.url}\n**Title:** ${tab.title}\n**Captured:** ${new Date().toISOString()}`,
        content_type: 'document',
        category: 'research',
        tags: ['web-capture', 'chrome']
      };
      try {
        const r = await fetch(`${nexusUrl}/entries`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(entry)
        });
        statusEl.textContent = r.ok ? '✓ Page sent to Nexus' : '✗ Failed to send';
        statusEl.className = r.ok ? 'status ok' : 'status err';
      } catch {
        statusEl.textContent = '✗ Nexus unreachable';
        statusEl.className = 'status err';
      }
    }
  });

  document.getElementById('options').addEventListener('click', () => {
    chrome.runtime.openOptionsPage();
  });
});
