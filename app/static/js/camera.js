(() => {
  const video = document.getElementById('camera-video');
  if (!video) return;
  const canvas = document.getElementById('capture-canvas');
  const placeholder = document.getElementById('camera-placeholder');
  const sessionSelect = document.getElementById('session-select');
  const startBtn = document.getElementById('camera-start');
  const scanBtn = document.getElementById('camera-scan');
  const stopBtn = document.getElementById('camera-stop');
  const status = document.getElementById('scan-status');
  let stream = null;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';

  function setStatus(message, kind = '') {
    status.textContent = message;
    status.className = `scan-status ${kind}`;
  }
  async function startCamera() {
    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus('Camera access is unavailable. Use HTTPS or localhost in a supported browser.', 'error'); return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });
      video.srcObject = stream;
      await video.play();
      placeholder.hidden = true;
      startBtn.disabled = true; scanBtn.disabled = !sessionSelect.value; stopBtn.disabled = false;
      setStatus('Camera ready. Select a session and scan one face.', 'success');
    } catch (err) {
      setStatus(`Could not access the camera: ${err.message || 'permission denied'}`, 'error');
    }
  }
  function stopCamera() {
    if (stream) stream.getTracks().forEach(track => track.stop());
    stream = null; video.srcObject = null; placeholder.hidden = false;
    startBtn.disabled = false; scanBtn.disabled = true; stopBtn.disabled = true;
    setStatus('Camera stopped.');
  }
  async function scan() {
    if (!stream || !sessionSelect.value || !video.videoWidth) {
      setStatus('Start the camera and choose an open session first.', 'error'); return;
    }
    scanBtn.disabled = true;
    setStatus('Analyzing face… keep still for a moment.');
    canvas.width = video.videoWidth; canvas.height = video.videoHeight;
    const context = canvas.getContext('2d', { willReadFrequently: true });
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const image = canvas.toDataURL('image/jpeg', 0.88);
    try {
      const response = await fetch('/api/recognize', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify({ session_id: sessionSelect.value, image })
      });
      const result = await response.json();
      if (result.ok) {
        setStatus(`${result.message} Match score: ${result.score}.`, result.duplicate ? 'warning' : 'success');
      } else {
        setStatus(`${result.message || 'Recognition failed.'}${result.score !== undefined ? ` Score: ${result.score}.` : ''}`, 'error');
      }
    } catch (err) {
      setStatus(`Request failed: ${err.message || 'network error'}`, 'error');
    } finally {
      scanBtn.disabled = !stream || !sessionSelect.value;
    }
  }
  startBtn.addEventListener('click', startCamera);
  stopBtn.addEventListener('click', stopCamera);
  scanBtn.addEventListener('click', scan);
  sessionSelect.addEventListener('change', () => { scanBtn.disabled = !stream || !sessionSelect.value; });
  window.addEventListener('beforeunload', stopCamera);
})();
