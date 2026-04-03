// ─────────────────────────────────────────────────────────────
// WebSocket connection
// ─────────────────────────────────────────────────────────────
const socket = io();

socket.on('connect', () => {
  console.log('✅ WebSocket connected:', socket.id);
});

socket.on('disconnect', () => {
  console.warn('⚠️ WebSocket disconnected — attempting reconnect…');
});

socket.on('connect_error', (err) => {
  console.error('❌ WebSocket connection error:', err.message);
});


// ─────────────────────────────────────────────────────────────
// PPE status update — replaces setInterval(updateStatus, 3000)
// ─────────────────────────────────────────────────────────────
socket.on('ppe_update', (data) => {
  console.log('📡 ppe_update received:', data);
  updateStatusDisplay(data);
});


// ─────────────────────────────────────────────────────────────
// Gate state update — replaces relay polling
// ─────────────────────────────────────────────────────────────
socket.on('gate_update', (data) => {
  console.log('🚪 gate_update received:', data);

  const relayBadge = document.getElementById('relay-status');
  if (relayBadge) {
    relayBadge.textContent = data.relay || 'UNKNOWN';
    relayBadge.classList.toggle('relay-open',   data.relay === 'OPEN');
    relayBadge.classList.toggle('relay-closed', data.relay === 'CLOSED');
  }
});


// ─────────────────────────────────────────────────────────────
// New event log entry — replaces setInterval(updateEvents, 5000)
// ─────────────────────────────────────────────────────────────
socket.on('new_event', (evt) => {
  console.log('📋 new_event received:', evt);
  prependEvent(evt);
});


// ─────────────────────────────────────────────────────────────
// Display helpers
// ─────────────────────────────────────────────────────────────

/**
 * Update a single PPE checklist row.
 *
 * Three states, driven by the YOLO negative-class fields:
 *   violation  (no_helmet / no_gloves / no_boots detected)
 *     → red dot  + red  ✕  icon
 *   present    (helmet / gloves / boots detected, no violation)
 *     → green dot + green ✓ icon
 *   unknown    (neither — empty frame / no person)
 *     → grey dot  + grey  – icon
 *
 * The old code only toggled a CSS class on the wrapper div and
 * never touched the icon elements, so colours never actually changed.
 */
function updatePpeItem(el, present, violation) {
  if (!el) return;

  const dot  = el.querySelector('i:first-child');   // the filled-circle dot
  const icon = el.querySelector('i:last-child');     // the status icon on the right

  // Strip all possible state classes from both icons
  const allColors = ['text-success', 'text-danger', 'text-secondary'];
  const allIcons  = ['bi-check-lg', 'bi-x-lg', 'bi-dash-lg'];

  if (dot)  dot.classList.remove(...allColors);
  if (icon) { icon.classList.remove(...allColors, ...allIcons); }

  if (violation) {
    // ❌ PPE missing — person detected WITHOUT this item
    dot?.classList.add('text-danger');
    icon?.classList.add('bi-x-lg', 'text-danger');
  } else if (present) {
    // ✅ PPE present
    dot?.classList.add('text-success');
    icon?.classList.add('bi-check-lg', 'text-success');
  } else {
    // ❓ No person / unknown
    dot?.classList.add('text-secondary');
    icon?.classList.add('bi-dash-lg', 'text-secondary');
  }
}

function updateStatusDisplay(data) {
  // ── Main status alert ────────────────────────────────────────
  const mainStatus = document.getElementById('main-status');
  if (mainStatus) {
    if (data.ppe_status === 'OK') {
      mainStatus.innerHTML = `
        <div class="alert alert-success d-flex align-items-center" role="alert">
          <i class="bi bi-check-circle-fill me-2 fs-4"></i>
          <div><strong>ALL CLEAR</strong><br><small>PPE Compliance Verified</small></div>
        </div>`;
    } else if (data.ppe_status === 'NOT_OK') {
      mainStatus.innerHTML = `
        <div class="alert alert-danger d-flex align-items-center" role="alert">
          <i class="bi bi-exclamation-triangle-fill me-2 fs-4"></i>
          <div><strong>VIOLATION DETECTED</strong><br><small>Missing PPE detected</small></div>
        </div>`;
    } else {
      mainStatus.innerHTML = `
        <div class="alert alert-warning d-flex align-items-center" role="alert">
          <i class="bi bi-question-circle-fill me-2 fs-4"></i>
          <div><strong>UNKNOWN</strong><br><small>Waiting for detection</small></div>
        </div>`;
    }
  }

  // ── Individual PPE item rows ─────────────────────────────────
  // Use the negative-class fields (no_helmet etc.) for accurate violation
  // detection. Fall back gracefully if backend hasn't sent them yet.
  updatePpeItem(
    document.getElementById('helmet-status'),
    !!data.helmet,
    !!data.no_helmet
  );
  updatePpeItem(
    document.getElementById('gloves-status'),
    !!data.gloves,
    !!data.no_gloves
  );
  updatePpeItem(
    document.getElementById('boots-status'),
    !!data.boots,
    !!data.no_boots
  );

  // ── Last updated timestamp ───────────────────────────────────
  const lastUpdatedEl = document.getElementById('last-updated');
  if (lastUpdatedEl && data.last_updated) {
    lastUpdatedEl.textContent = data.last_updated;
  }
}


function prependEvent(evt) {
  const list = document.getElementById('event-list');
  if (!list) return;

  const li = document.createElement('li');
  li.className = `event-item event-${evt.type}`;
  li.innerHTML = `
    <span class="event-time">${evt.time}</span>
    <span class="event-message">${evt.message}</span>
  `;

  // Add to top, keep max 10 entries
  list.insertBefore(li, list.firstChild);
  while (list.children.length > 10) {
    list.removeChild(list.lastChild);
  }
}


// ─────────────────────────────────────────────────────────────
// Initial page load — fetch current state once via HTTP
// This ensures the page shows correct state on first load
// before any WebSocket events arrive
// ─────────────────────────────────────────────────────────────
function loadInitialState() {
  // Load current PPE status
  fetch('/status')
    .then(res => res.json())
    .then(data => {
      updateStatusDisplay(data);

      // Relay badge
      const relayBadge = document.getElementById('relay-status');
      if (relayBadge) {
        relayBadge.textContent = data.relay || 'UNKNOWN';
        relayBadge.classList.toggle('relay-open',   data.relay === 'OPEN');
        relayBadge.classList.toggle('relay-closed', data.relay === 'CLOSED');
      }

      // Override badge
      const overrideBadge = document.getElementById('override-badge');
      if (overrideBadge) {
        if (data.override) {
          overrideBadge.textContent = 'OVERRIDE ACTIVE';
          overrideBadge.classList.add('override-on');
          overrideBadge.classList.remove('override-off');
        } else {
          overrideBadge.textContent = 'AUTO MODE';
          overrideBadge.classList.remove('override-on');
          overrideBadge.classList.add('override-off');
        }
      }

      // Cooldown
      const cooldownBox = document.getElementById('cooldown-box');
      const cooldownSec = document.getElementById('cooldown-seconds');
      if (cooldownBox && cooldownSec) {
        if (data.cooldown_active) {
          cooldownBox.classList.remove('d-none');
          cooldownSec.textContent = data.cooldown_remaining;
        } else {
          cooldownBox.classList.add('d-none');
        }
      }
    })
    .catch(err => console.error('Error loading initial status:', err));

  // Load recent events
  fetch('/events')
    .then(res => res.json())
    .then(events => {
      const list = document.getElementById('event-list');
      if (!list) return;
      list.innerHTML = '';
      events.slice().reverse().forEach(evt => prependEvent(evt));
    })
    .catch(err => console.error('Error loading initial events:', err));
  
  fetch('/api/stats')
  .then(res => res.json())
  .then(data => {
    const v = document.getElementById('stat-violations');
    const c = document.getElementById('stat-captures');
    const e = document.getElementById('stat-entries');
    if (v) v.textContent = data.violations_today;
    if (c) c.textContent = data.captures_today;
    if (e) e.textContent = data.entries_today;
  })
  .catch(err => console.error('Stats error:', err));
}


// ─────────────────────────────────────────────────────────────
// Relay / gate manual controls  (unchanged from original)
// ─────────────────────────────────────────────────────────────
function initRelayControls() {
  const relayBtn = document.getElementById('relay-toggle-btn');
  if (!relayBtn) return;

  relayBtn.addEventListener('click', () => {
    fetch('/control/relay', { method: 'POST' })
      .then(res => res.json())
      .then(data => {
        const relayBadge = document.getElementById('relay-status');
        if (relayBadge) {
          relayBadge.textContent = data.relay;
          relayBadge.classList.toggle('relay-open',   data.relay === 'OPEN');
          relayBadge.classList.toggle('relay-closed', data.relay === 'CLOSED');
        }

        const overrideBadge = document.getElementById('override-badge');
        const overrideMsg   = document.getElementById('override-message');
        if (overrideBadge && data.override) {
          overrideBadge.textContent = 'OVERRIDE ACTIVE';
          overrideBadge.classList.add('override-on');
          overrideBadge.classList.remove('override-off');
        }
        if (overrideMsg && data.message) {
          overrideMsg.textContent = data.message;
        }
      })
      .catch(err => console.error('Error toggling relay:', err));
  });

  const autoBtn = document.getElementById('auto-mode-btn');
  if (autoBtn) {
    autoBtn.addEventListener('click', () => {
      fetch('/control/auto', { method: 'POST' })
        .then(res => res.json())
        .then(data => {
          const overrideBadge = document.getElementById('override-badge');
          const overrideMsg   = document.getElementById('override-message');
          if (overrideBadge) {
            overrideBadge.textContent = 'AUTO MODE';
            overrideBadge.classList.remove('override-on');
            overrideBadge.classList.add('override-off');
          }
          if (overrideMsg && data.message) {
            overrideMsg.textContent = data.message;
          }
        });
    });
  }
}

// ─────────────────────────────────────────────────────────────
// Override / auto mode state update
// ─────────────────────────────────────────────────────────────
// Local cooldown timer reference
let cooldownTimer = null;

socket.on('override_update', (data) => {
  console.log('🔧 override_update received:', data);

  const relayBadge    = document.getElementById('relay-status');
  const overrideBadge = document.getElementById('override-badge');
  const overrideMsg   = document.getElementById('override-message');
  const cooldownBox   = document.getElementById('cooldown-box');
  const cooldownSec   = document.getElementById('cooldown-seconds');

  if (relayBadge) {
    relayBadge.textContent = data.relay || 'UNKNOWN';
    relayBadge.classList.toggle('relay-open',   data.relay === 'OPEN');
    relayBadge.classList.toggle('relay-closed', data.relay === 'CLOSED');
  }

  if (overrideBadge) {
    if (data.override) {
      overrideBadge.textContent = 'OVERRIDE ACTIVE';
      overrideBadge.classList.add('override-on');
      overrideBadge.classList.remove('override-off');
    } else {
      overrideBadge.textContent = 'AUTO MODE';
      overrideBadge.classList.remove('override-on');
      overrideBadge.classList.add('override-off');
    }
  }

  if (overrideMsg && data.message) {
    overrideMsg.textContent = data.message;
  }

  // Handle cooldown countdown locally
  if (cooldownBox && cooldownSec) {
    if (data.cooldown_active && data.cooldown_remaining > 0) {
      cooldownBox.classList.remove('d-none');
      cooldownSec.textContent = data.cooldown_remaining;

      // Clear any existing timer
      if (cooldownTimer) clearInterval(cooldownTimer);

      let remaining = data.cooldown_remaining;
      cooldownTimer = setInterval(() => {
        remaining -= 1;
        if (remaining <= 0) {
          clearInterval(cooldownTimer);
          cooldownTimer = null;
          cooldownBox.classList.add('d-none');
        } else {
          cooldownSec.textContent = Math.round(remaining);
        }
      }, 1000);

    } else {
      // No cooldown — hide box and clear any running timer
      if (cooldownTimer) {
        clearInterval(cooldownTimer);
        cooldownTimer = null;
      }
      cooldownBox.classList.add('d-none');
    }
  }
});


// ─────────────────────────────────────────────────────────────
// Yard PPE Alert — banner + siren beep + acknowledge
// ─────────────────────────────────────────────────────────────
let _currentAlertId = null;

function playAlertBeep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();

    // Deep urgent alarm — two low-frequency tones alternating (industrial buzzer style).
    // Low frequencies (100–140 Hz) carry far better on laptop speakers than high beeps.
    const tones = [130, 110];   // Hz — deep bass (C3 / A2 range)

    tones.forEach((freq, i) => {
      const osc    = ctx.createOscillator();
      const gain   = ctx.createGain();
      const shaper = ctx.createWaveShaper();

      // Mild waveshaper adds odd harmonics — makes low tones feel fuller/punchier
      const curve = new Float32Array(256);
      for (let j = 0; j < 256; j++) {
        const x = (j * 2) / 256 - 1;
        curve[j] = (Math.PI + 200) * x / (Math.PI + 200 * Math.abs(x));
      }
      shaper.curve = curve;

      osc.connect(shaper);
      shaper.connect(gain);
      gain.connect(ctx.destination);

      osc.type            = 'square';  // square wave — rich harmonics at low freq
      osc.frequency.value = freq;

      const start    = ctx.currentTime + i * 0.55;  // 550ms gap between the two tones
      const duration = 0.45;                         // each tone holds for 450ms

      gain.gain.setValueAtTime(0, start);
      gain.gain.linearRampToValueAtTime(0.8, start + 0.03);    // fast attack
      gain.gain.setValueAtTime(0.8, start + duration - 0.06);  // sustain
      gain.gain.linearRampToValueAtTime(0, start + duration);  // smooth decay

      osc.start(start);
      osc.stop(start + duration);
    });

  } catch (e) {
    console.warn('Audio not available:', e);
  }
}

function showYardAlertBanner(data) {
  _currentAlertId = data.alert_id;

  document.getElementById('yard-alert-camera').textContent = data.camera_name || '';
  document.getElementById('yard-alert-time').textContent   = data.time || '';

  // Render missing items as pill badges
  const missingEl = document.getElementById('yard-alert-missing');
  const items = Array.isArray(data.missing) ? data.missing : [data.missing];
  missingEl.innerHTML = items
    .filter(Boolean)
    .map(item => `<span class="yard-missing-badge">${item}</span>`)
    .join('');

  // Thumbnail
  const thumb = document.getElementById('yard-alert-thumb');
  if (data.image) {
    thumb.src           = `/violation-image/${data.image}`;
    thumb.style.display = 'inline-block';
  } else {
    thumb.style.display = 'none';
  }

  // Reset acknowledge button
  const ackBtn = document.getElementById('yard-alert-ack-btn');
  if (ackBtn) {
    ackBtn.disabled   = false;
    ackBtn.innerHTML  = '<i class="bi bi-check-circle-fill me-1"></i> Acknowledge';
  }

  // Show banner and push content down
  const banner  = document.getElementById('yard-alert-banner');
  const content = document.getElementById('main-content');
  banner.style.display = 'block';
  if (content) content.style.paddingTop = (banner.offsetHeight + 16) + 'px';
}

function hideYardAlertBanner() {
  const banner  = document.getElementById('yard-alert-banner');
  const content = document.getElementById('main-content');
  if (banner)  banner.style.display = 'none';
  if (content) content.style.paddingTop = '';
  _currentAlertId = null;
}

socket.on('yard_alert', (data) => {
  console.log('🚨 yard_alert received:', data);
  playAlertBeep();
  showYardAlertBanner(data);
});

// Wire acknowledge button on every page
document.addEventListener('DOMContentLoaded', () => {
  const ackBtn = document.getElementById('yard-alert-ack-btn');
  if (!ackBtn) return;
  ackBtn.addEventListener('click', () => {
    if (_currentAlertId === null) return;
    ackBtn.disabled  = true;
    ackBtn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i> Saving…';
    fetch(`/yard-alerts/${_currentAlertId}/acknowledge`, { method: 'POST' })
      .then(res => res.json())
      .then(data => {
        if (data.status === 'success') {
          hideYardAlertBanner();
        } else {
          ackBtn.disabled  = false;
          ackBtn.innerHTML = '<i class="bi bi-check-circle-fill me-1"></i> Acknowledge';
        }
      })
      .catch(() => {
        ackBtn.disabled  = false;
        ackBtn.innerHTML = '<i class="bi bi-check-circle-fill me-1"></i> Acknowledge';
      });
  });
});


// ─────────────────────────────────────────────────────────────
// Boot
// ─────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  loadInitialState();
  initRelayControls();
});