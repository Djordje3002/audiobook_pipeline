const statusEl = document.getElementById('status');

async function postJSON(url, body) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return response.json();
}

document.getElementById('runPreview')?.addEventListener('click', async () => {
  const result = await postJSON('/api/preview', { source_path: 'input_audio/book.mp3' });
  statusEl.textContent = JSON.stringify(result, null, 2);
});

document.getElementById('runFull')?.addEventListener('click', async () => {
  const result = await postJSON('/api/full', { source_path: 'input_audio/book.mp3' });
  statusEl.textContent = JSON.stringify(result, null, 2);
});
