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
                    <div class="alert alert-success d-flex align-items-center" role="alert">
                        <i class="bi bi-check-circle-fill me-2 fs-4"></i>
                        <div>
                            <strong>ALL CLEAR</strong><br>
                            <small>PPE Compliance Verified</small>
                        </div>
                    </div>
                `;
            } else {
                mainStatus.innerHTML = `
                    <div class="alert alert-danger d-flex align-items-center" role="alert">
                        <i class="bi bi-exclamation-triangle-fill me-2 fs-4"></i>
                        <div>
                            <strong>PPE VIOLATION</strong><br>
                            <small>Missing Required Equipment</small>
                        </div>
                    </div>
                `;
            }

            // Update individual items
            updatePPEItem('helmet-status', data.helmet);
            updatePPEItem('vest-status', data.vest);
            updatePPEItem('gloves-status', data.gloves);

            // Update relay
            const relayIndicator = document.getElementById('relay-indicator');
            const relayClass = data.relay === 'OPEN' ? 'bg-secondary' : 'bg-danger';
            relayIndicator.innerHTML = `<span class="badge ${relayClass} fs-6 px-4 py-2">GATE: ${data.relay}</span>`;

            // Update timestamp
            document.getElementById('last-updated').textContent = data.last_updated;
        })
        .catch(error => console.error('Error fetching status:', error));
}

function updatePPEItem(elementId, isPresent) {
    const element = document.getElementById(elementId);
    const statusClass = isPresent ? 'text-success' : 'text-danger';
    const icon = isPresent ? 'bi-check-lg' : 'bi-x-lg';
    
    const circleIcon = element.querySelector('.bi-circle-fill');
    const checkIcon = element.querySelector('.ms-auto');
    
    circleIcon.className = `bi bi-circle-fill ${statusClass}`;
    checkIcon.className = `bi ${icon} ${statusClass} ms-auto`;
}

function loadEvents() {
    fetch('/events')
        .then(response => response.json())
        .then(events => {
            const eventLog = document.getElementById('event-log');
            eventLog.innerHTML = events.map(event => {
                const iconClass = event.type === 'success' ? 'text-success bi-check-circle-fill' : 'text-warning bi-exclamation-circle-fill';
                return `
                    <div class="event-item">
                        <i class="bi ${iconClass}"></i>
                        <span class="event-time">${event.time}</span>
                        <span class="event-message">${event.message}</span>
                    </div>
                `;
            }).join('');
        })
        .catch(error => console.error('Error loading events:', error));
}

// Relay toggle
document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('relay-toggle').addEventListener('click', function() {
        fetch('/control/relay', { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                updateStatus();
            })
            .catch(error => console.error('Error toggling relay:', error));
    });

    // Initial load
    updateStatus();
    loadEvents();

    // Start auto-refresh
    statusInterval = setInterval(updateStatus, 3000);
    eventsInterval = setInterval(loadEvents, 5000);
});
