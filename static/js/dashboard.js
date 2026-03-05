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
// Display helpers  (logic identical to old polling version)
// ─────────────────────────────────────────────────────────────
function updateStatusDisplay(data) {
  // Main status alert
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

  // Individual PPE item indicators
  const helmetEl = document.getElementById('helmet-status');
  const glovesEl = document.getElementById('gloves-status');
  const bootsEl  = document.getElementById('boots-status');

  if (helmetEl) {
    helmetEl.classList.toggle('ok',  data.helmet);
    helmetEl.classList.toggle('bad', !data.helmet);
  }
  if (glovesEl) {
    glovesEl.classList.toggle('ok',  data.gloves);
    glovesEl.classList.toggle('bad', !data.gloves);
  }
  if (bootsEl) {
    bootsEl.classList.toggle('ok',  data.boots);
    bootsEl.classList.toggle('bad', !data.boots);
  }

  // Last updated timestamp
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
          cooldownSec.textContent = remaining;
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
// Boot
// ─────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  loadInitialState();
  initRelayControls();
});