// Auto-refresh status every 3 seconds
let statusInterval;
let eventsInterval;

function updateStatus() {
  fetch('/status')
    .then(response => response.json())
    .then(data => {
      // Update main status
      const mainStatus = document.getElementById('main-status');
      if (data.ppe_status === 'OK') {
        mainStatus.innerHTML = `
          <span class="status-pill status-ok">SAFE</span>
          <span class="status-subtext">All PPE detected</span>
        `;
      } else if (data.ppe_status === 'NOT_OK') {
        mainStatus.innerHTML = `
          <span class="status-pill status-bad">UNSAFE</span>
          <span class="status-subtext">Missing PPE detected</span>
        `;
      } else {
        mainStatus.innerHTML = `
          <span class="status-pill status-unknown">UNKNOWN</span>
          <span class="status-subtext">Waiting for detection</span>
        `;
      }

      // Update individual PPE indicators
      const helmetEl = document.getElementById('helmet-status');
      const glovesEl = document.getElementById('gloves-status');
      const bootsEl = document.getElementById('boots-status');



      if (data.helmet) {
        helmetEl.classList.add('ok');
        helmetEl.classList.remove('bad');
      } else {
        helmetEl.classList.add('bad');
        helmetEl.classList.remove('ok');
      }

      if (data.gloves) {
        glovesEl.classList.add('ok');
        glovesEl.classList.remove('bad');
      } else {
        glovesEl.classList.add('bad');
        glovesEl.classList.remove('ok');
      }
      
      if (data.boots) {
        bootsEl.classList.add('ok');
        bootsEl.classList.remove('bad');
      } else {
        bootsEl.classList.add('bad');
        bootsEl.classList.remove('ok');
      }

      // Update relay badge
      const relayBadge = document.getElementById('relay-status');
      relayBadge.textContent = data.relay || 'UNKNOWN';
      relayBadge.classList.toggle('relay-open', data.relay === 'OPEN');
      relayBadge.classList.toggle('relay-closed', data.relay === 'CLOSED');

      // Show override indicator + message area
      const overrideBadge = document.getElementById('override-badge');
      const overrideMsg = document.getElementById('override-message');

      if (data.override) {
        overrideBadge.textContent = 'OVERRIDE ACTIVE';
        overrideBadge.classList.add('override-on');
        overrideBadge.classList.remove('override-off');
        // Keep existing text; actual message comes from /control/relay
        if (!overrideMsg.textContent) {
          overrideMsg.textContent = 'Manual override in effect';
        }
      } else {
        overrideBadge.textContent = 'AUTO MODE';
        overrideBadge.classList.remove('override-on');
        overrideBadge.classList.add('override-off');
        // Do not clear overrideMsg, so the last action is still visible
      }

      // Last updated
      const lastUpdatedEl = document.getElementById('last-updated');
      if (lastUpdatedEl && data.last_updated) {
        lastUpdatedEl.textContent = data.last_updated;
      }
    })
    .catch(err => {
      console.error('Error updating status:', err);
    });
}

function updateEvents() {
  fetch('/events')
    .then(response => response.json())
    .then(events => {
      const list = document.getElementById('event-list');
      if (!list) return;

      list.innerHTML = '';

      events.slice().reverse().forEach(evt => {
        const li = document.createElement('li');
        li.className = `event-item event-${evt.type}`;
        li.innerHTML = `
          <span class="event-time">${evt.time}</span>
          <span class="event-message">${evt.message}</span>
        `;
        list.appendChild(li);
      });
    })
    .catch(err => {
      console.error('Error updating events:', err);
    });
}

function initRelayControls() {
  const relayBtn = document.getElementById('relay-toggle-btn');
  if (!relayBtn) return;

  relayBtn.addEventListener('click', () => {
    fetch('/control/relay', {
      method: 'POST',
    })
      .then(res => res.json())
      .then(data => {
        // Update relay badge
        const relayBadge = document.getElementById('relay-status');
        relayBadge.textContent = data.relay;
        relayBadge.classList.toggle('relay-open', data.relay === 'OPEN');
        relayBadge.classList.toggle('relay-closed', data.relay === 'CLOSED');

        // Show override state
        const overrideBadge = document.getElementById('override-badge');
        const overrideMsg = document.getElementById('override-message');

        if (data.override) {
          overrideBadge.textContent = 'OVERRIDE ACTIVE';
          overrideBadge.classList.add('override-on');
          overrideBadge.classList.remove('override-off');
        }

        // Show the server message, e.g.
        // "Manual override: gate OPENED by supervisor"
        // "Manual override: gate CLOSED by supervisor"
        if (overrideMsg && data.message) {
          overrideMsg.textContent = data.message;
        }
      })
      .catch(err => {
        console.error('Error toggling relay:', err);
      });
  });

  const autoBtn = document.getElementById('auto-mode-btn');
  if (autoBtn) {
    autoBtn.addEventListener('click', () => {
      fetch('/control/auto', { method: 'POST' })
        .then(res => res.json())
        .then(data => {
          const overrideBadge = document.getElementById('override-badge');
          const overrideMsg = document.getElementById('override-message');
          overrideBadge.textContent = 'AUTO MODE';
          overrideBadge.classList.remove('override-on');
          overrideBadge.classList.add('override-off');
          if (data.message) overrideMsg.textContent = data.message;
        });
    });
  }
}

// Initialize on load
window.addEventListener('DOMContentLoaded', () => {
  updateStatus();
  updateEvents();
  initRelayControls();

  statusInterval = setInterval(updateStatus, 3000);
  eventsInterval = setInterval(updateEvents, 5000);
});
