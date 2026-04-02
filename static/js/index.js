(() => {
    const connectionEl = document.getElementById('connection-status');
    const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const wsUrl = `${wsProtocol}://${window.location.host}/ws`;
    let ws = null;
    let reconnectTimer = null;

    function formatKcalDisplay(value) {
        const num = Number(value);
        return Number.isFinite(num) ? num.toFixed(1) : '0.0';
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

    function updateHeartRateUI(data) {
        if (!data || data.device_id === undefined || data.device_id === null) {
            return;
        }
        const card = document.querySelector(`.device_card[data-device-id="${data.device_id}"]`);
        if (!card) {
            return;
        }
        const hrEl = card.querySelector('.metric_value.hr');
        const kcalEl = card.querySelector('.metric_value.kcal');
        const timeEl = card.querySelector('.device_time');
        if (hrEl) hrEl.textContent = data.hr ?? '—';
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
    connect();
})();
