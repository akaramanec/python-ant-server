(() => {
    const connectionEl = document.getElementById('connection-status');
    const cardsGridEl = document.getElementById('cards-grid');
    const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const wsUrl = `${wsProtocol}://${window.location.host}/ws`;
    const caloriesOffset = (() => {
        const raw = new URLSearchParams(window.location.search).get('calories_offset');
        const parsed = Number(raw);
        return Number.isFinite(parsed) ? parsed : 0;
    })();
    const heartrateOffset = (() => {
        const raw = new URLSearchParams(window.location.search).get('heartrate_offset');
        const parsed = Number(raw);
        return Number.isFinite(parsed) ? parsed : 0;
    })();
    let ws = null;
    let reconnectTimer = null;

    function formatKcalDisplay(value) {
        const num = Number(value) + caloriesOffset;
        return Number.isFinite(num) ? num.toFixed(1) : '0.0';
    }

    function formatHrDisplay(value) {
        const num = Number(value);
        if (!Number.isFinite(num)) return '—';
        return String(Math.round(num + heartrateOffset));
    }

    function parseDateTimeFlexible(value) {
        if (!value) return null;
        let s = String(value).trim();
        if (!s) return null;
        if (s.endsWith('Z')) s = `${s.slice(0, -1)}+00:00`;
        if (s.length >= 19 && s[10] === ' ') {
            s = `${s.slice(0, 10)}T${s.slice(11)}`;
        } else if (s.includes(' ') && !s.slice(0, 11).includes('T')) {
            s = s.replace(' ', 'T');
        }
        const ms = Date.parse(s);
        return Number.isNaN(ms) ? null : new Date(ms);
    }

    function formatFitnessTimeFromStart(startAtValue) {
        const startDt = parseDateTimeFlexible(startAtValue);
        if (!startDt) return '0:00:00';
        const sec = Math.max(0, Math.floor((Date.now() - startDt.getTime()) / 1000));
        const h = Math.floor(sec / 3600);
        const m = Math.floor((sec % 3600) / 60);
        const s = sec % 60;
        return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }

    function bootstrapInitialFitnessTime() {
        document.querySelectorAll('.device_card').forEach((card) => {
            const timeEl = card.querySelector('.device_time');
            if (!timeEl) return;
            const startAt = card.dataset.startAt || '';
            timeEl.textContent = formatFitnessTimeFromStart(startAt);
        });
    }

    function syncCardsDensityClass() {
        if (!cardsGridEl) return;
        const count = cardsGridEl.querySelectorAll('.device_card').length;
        cardsGridEl.classList.remove('cards-more-than-20', 'cards-more-than-30');
        if (count > 30) {
            cardsGridEl.classList.add('cards-more-than-30');
        } else if (count > 20) {
            cardsGridEl.classList.add('cards-more-than-20');
        } else {
            // <=20: базовий cards-grid без додаткового класу
        }
    }

    function createDeviceCard(data) {
        if (!cardsGridEl) return null;
        const card = document.createElement('div');
        card.className = 'device_card';
        card.dataset.deviceId = String(data.device_id);
        card.dataset.startAt = '';
        card.innerHTML = `
            <div class="device_name_zone">
                <div class="device_last_name"></div>
            </div>
            <div class="device_metrics_row">
                <div class="metric_block hr_block">
                    <img class="metric_icon" src="/static/images/heart.png" alt="" aria-hidden="true" />
                    <div class="metric_value hr">—</div>
                </div>
                <div class="metric_block kcal_block">
                    <img class="metric_icon" src="/static/images/flame.png" alt="" aria-hidden="true" />
                    <div class="metric_value kcal">0.0</div>
                </div>
            </div>
            <div class="device_time">0:00:00</div>
        `;
        const lastNameEl = card.querySelector('.device_last_name');
        if (lastNameEl) {
            lastNameEl.textContent = data.last_name || '';
        }
        cardsGridEl.appendChild(card);
        syncCardsDensityClass();
        return card;
    }

    function removeDeviceCard(deviceId) {
        const card = document.querySelector(`.device_card[data-device-id="${deviceId}"]`);
        if (!card) return;
        card.remove();
        syncCardsDensityClass();
    }

    function updateHeartRateUI(data) {
        if (!data || data.device_id === undefined || data.device_id === null) {
            return;
        }
        const card = document.querySelector(`.device_card[data-device-id="${data.device_id}"]`) || createDeviceCard(data);
        if (!card) return;
        const hrEl = card.querySelector('.metric_value.hr');
        const kcalEl = card.querySelector('.metric_value.kcal');
        const timeEl = card.querySelector('.device_time');
        if (hrEl) hrEl.textContent = formatHrDisplay(data.hr);
        if (kcalEl) kcalEl.textContent = formatKcalDisplay(data.calories);
        if (timeEl) timeEl.textContent = data.fitness_time || '0:00:00';
    }

    function setConnectionState(isLive) {
        connectionEl.classList.toggle('live', isLive);
        connectionEl.classList.toggle('offline', !isLive);
        connectionEl.textContent = `Статус з'єднання: ${isLive ? 'LIVE (WebSocket)' : 'OFFLINE'}`;
    }

    function connect() {
        if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
            return;
        }
        ws = new WebSocket(wsUrl);
        ws.onopen = () => setConnectionState(true);
        ws.onmessage = (event) => {
            try {
                const payload = JSON.parse(event.data);
                if (payload.event === 'rental_stopped') {
                    removeDeviceCard(payload.device_id);
                    return;
                }
                if (payload.event) {
                    return;
                }
                updateHeartRateUI(payload);
            } catch (e) {
                console.warn('WS parse error:', e);
            }
        };
        ws.onclose = () => {
            setConnectionState(false);
            if (!reconnectTimer) {
                reconnectTimer = setTimeout(() => {
                    reconnectTimer = null;
                    connect();
                }, 3000);
            }
        };
        ws.onerror = () => ws.close();
    }

    setConnectionState(false);
    bootstrapInitialFitnessTime();
    syncCardsDensityClass();
    connect();
})();
