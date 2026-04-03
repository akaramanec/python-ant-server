let rentPairIsActive = false;
let rentalDataLoaded = false;
let trackersForNameModalCache = [];
let usersForUsersModalCache = [];
let historyDevicesCache = [];
let historyUsersCache = [];
let historyDeviceSelectedId = '';
let historyCustomerSelectedId = '';
let historySortBy = 'day';
let historySortDir = 'desc';

function updateHistorySortHeaders() {
    document.querySelectorAll('#history-table-head th.sortable').forEach((th) => {
        const key = th.dataset.sortKey;
        th.classList.remove('sorted', 'asc', 'desc');
        th.removeAttribute('aria-sort');
        if (key === historySortBy) {
            th.classList.add('sorted', historySortDir === 'asc' ? 'asc' : 'desc');
            th.setAttribute('aria-sort', historySortDir === 'asc' ? 'ascending' : 'descending');
        }
    });
}

function onHistorySortClick(sortKey) {
    if (sortKey === historySortBy) {
        historySortDir = historySortDir === 'asc' ? 'desc' : 'asc';
    } else {
        historySortBy = sortKey;
        if (sortKey === 'device_name' || sortKey === 'customer_fullname') {
            historySortDir = 'asc';
        } else {
            historySortDir = 'desc';
        }
    }
    updateHistorySortHeaders();
    loadHistory().catch((e) => console.error('Історія', e));
}

function escHtml(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function getHistoryDeviceLabel(t) {
    return `${t.name} (ID: ${t.device_id})`;
}

function getHistoryUserLabel(u) {
    return `${u.last_name} ${u.first_name} (ID: ${u.id})`;
}

function setHistoryDeviceById(id) {
    historyDeviceSelectedId = id ? String(id) : '';
    const input = document.getElementById('history-device-select');
    if (!historyDeviceSelectedId) {
        input.value = '';
        return;
    }
    const hit = historyDevicesCache.find((t) => String(t.device_id) === historyDeviceSelectedId);
    input.value = hit ? getHistoryDeviceLabel(hit) : '';
}

function setHistoryCustomerById(id) {
    historyCustomerSelectedId = id ? String(id) : '';
    const input = document.getElementById('history-customer-select');
    if (!historyCustomerSelectedId) {
        input.value = '';
        return;
    }
    const hit = historyUsersCache.find((u) => String(u.id) === historyCustomerSelectedId);
    input.value = hit ? getHistoryUserLabel(hit) : '';
}

function openHistoryMenu(menuId) {
    const menu = document.getElementById(menuId);
    menu.hidden = false;
}

function closeHistoryMenu(menuId) {
    const menu = document.getElementById(menuId);
    menu.hidden = true;
}

function renderHistoryDeviceMenu() {
    const input = document.getElementById('history-device-select');
    const menu = document.getElementById('history-device-menu');
    const q = input.value.trim().toLowerCase();
    const rows = historyDevicesCache.filter((t) => {
        const label = getHistoryDeviceLabel(t).toLowerCase();
        return !q || label.includes(q) || String(t.device_id).includes(q);
    });
    const listHtml = rows.map((t) => (
        `<button type="button" class="hist-combobox-option" data-id="${escHtml(String(t.device_id))}" data-label="${escHtml(getHistoryDeviceLabel(t))}">${escHtml(getHistoryDeviceLabel(t))}</button>`
    )).join('');
    menu.innerHTML = `<button type="button" class="hist-combobox-option hist-combobox-option-all" data-id="" data-label="">Усі трекери</button>${listHtml}`;
}

function renderHistoryUserMenu() {
    const input = document.getElementById('history-customer-select');
    const menu = document.getElementById('history-customer-menu');
    const q = input.value.trim().toLowerCase();
    const rows = historyUsersCache.filter((u) => {
        const label = getHistoryUserLabel(u).toLowerCase();
        return !q || label.includes(q) || String(u.id).includes(q);
    });
    const listHtml = rows.map((u) => (
        `<button type="button" class="hist-combobox-option" data-id="${escHtml(String(u.id))}" data-label="${escHtml(getHistoryUserLabel(u))}">${escHtml(getHistoryUserLabel(u))}</button>`
    )).join('');
    menu.innerHTML = `<button type="button" class="hist-combobox-option hist-combobox-option-all" data-id="" data-label="">Усі</button>${listHtml}`;
}

async function loadHistoryMeta() {
    const [trackers, users] = await Promise.all([
        fetchJson('/dashboard/trackers'),
        fetchJson('/dashboard/users'),
    ]);
    historyDevicesCache = trackers;
    historyUsersCache = users;
    setHistoryDeviceById(historyDeviceSelectedId);
    setHistoryCustomerById(historyCustomerSelectedId);
    renderHistoryDeviceMenu();
    renderHistoryUserMenu();
}

async function refreshActivePairsCount() {
    try {
        const data = await fetchJson('/dashboard/rentals/active-count');
        const value = Number(data.active_pairs);
        document.getElementById('active-pairs-count').textContent = Number.isFinite(value) ? String(value) : '0';
    } catch (e) {
        console.error('Активні пари', e);
        document.getElementById('active-pairs-count').textContent = '—';
    }
}

async function loadHistory() {
    const tbody = document.getElementById('history-table-body');
    tbody.innerHTML = '<tr><td colspan="5" class="history-empty">Завантаження…</td></tr>';
    const params = new URLSearchParams();
    const dev = historyDeviceSelectedId;
    const cust = historyCustomerSelectedId;
    const d = document.getElementById('history-filter-date').value;
    if (dev) params.set('device_id', dev);
    if (cust) params.set('customer_id', cust);
    if (d) params.set('filter_date', d);
    params.set('sort_by', historySortBy);
    params.set('sort_dir', historySortDir);
    params.set('limit', '500');
    try {
        const data = await fetchJson('/dashboard/history?' + params.toString());
        const rows = data.rows || [];
        if (rows.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="history-empty">Немає записів за умовами фільтра</td></tr>';
            return;
        }
        tbody.innerHTML = '';
        rows.forEach((row) => {
            const tr = document.createElement('tr');
            let dayStr = row.day ?? '';
            if (dayStr && /^\d{4}-\d{2}-\d{2}$/.test(dayStr)) {
                try {
                    const d = new Date(dayStr + 'T12:00:00');
                    if (!Number.isNaN(d.getTime())) {
                        dayStr = d.toLocaleDateString('uk-UA', { year: 'numeric', month: '2-digit', day: '2-digit' });
                    }
                } catch (e) { /* ignore */ }
            }
            const kcalStr = row.calories != null && row.calories !== ''
                ? Number(row.calories).toFixed(1)
                : '—';
            tr.innerHTML = `
                    <td>${escHtml(dayStr)}</td>
                    <td>${escHtml(row.device_name ?? '')}</td>
                    <td>${escHtml(row.customer_fullname ?? '')}</td>
                    <td class="num">${escHtml(row.training_time ?? '0:00:00')}</td>
                    <td class="num">${escHtml(kcalStr)}</td>`;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error(e);
        tbody.innerHTML = '<tr><td colspan="5" class="history-empty">Помилка завантаження</td></tr>';
    }
}

async function resetHistoryFiltersAndSort() {
    document.getElementById('history-device-select').value = '';
    document.getElementById('history-customer-select').value = '';
    document.getElementById('history-filter-date').value = '';
    historyDeviceSelectedId = '';
    historyCustomerSelectedId = '';
    historySortBy = 'day';
    historySortDir = 'desc';
    renderHistoryDeviceMenu();
    renderHistoryUserMenu();
    updateHistorySortHeaders();
    await loadHistory();
}

function initHistorySection() {
    updateHistorySortHeaders();
    document.getElementById('history-table-head').addEventListener('click', (e) => {
        const th = e.target.closest('th.sortable');
        if (!th || !th.dataset.sortKey) return;
        e.preventDefault();
        onHistorySortClick(th.dataset.sortKey);
    });
    const devInput = document.getElementById('history-device-select');
    const devMenu = document.getElementById('history-device-menu');
    const devToggle = document.getElementById('history-device-toggle');
    const custInput = document.getElementById('history-customer-select');
    const custMenu = document.getElementById('history-customer-menu');
    const custToggle = document.getElementById('history-customer-toggle');
    const dateInput = document.getElementById('history-filter-date');
    const dateBtn = document.getElementById('history-date-btn');

    devInput.addEventListener('focus', () => {
        renderHistoryDeviceMenu();
        openHistoryMenu('history-device-menu');
    });
    devInput.addEventListener('input', () => {
        historyDeviceSelectedId = '';
        renderHistoryDeviceMenu();
        openHistoryMenu('history-device-menu');
    });
    devToggle.addEventListener('click', () => {
        renderHistoryDeviceMenu();
        devMenu.hidden ? openHistoryMenu('history-device-menu') : closeHistoryMenu('history-device-menu');
        devInput.focus();
    });
    devInput.addEventListener('blur', () => setTimeout(() => closeHistoryMenu('history-device-menu'), 120));
    devMenu.addEventListener('mousedown', (e) => e.preventDefault());
    devMenu.addEventListener('click', (e) => {
        const btn = e.target.closest('.hist-combobox-option');
        if (!btn) return;
        setHistoryDeviceById(btn.dataset.id || '');
        closeHistoryMenu('history-device-menu');
    });

    custInput.addEventListener('focus', () => {
        renderHistoryUserMenu();
        openHistoryMenu('history-customer-menu');
    });
    custInput.addEventListener('input', () => {
        historyCustomerSelectedId = '';
        renderHistoryUserMenu();
        openHistoryMenu('history-customer-menu');
    });
    custToggle.addEventListener('click', () => {
        renderHistoryUserMenu();
        custMenu.hidden ? openHistoryMenu('history-customer-menu') : closeHistoryMenu('history-customer-menu');
        custInput.focus();
    });
    custInput.addEventListener('blur', () => setTimeout(() => closeHistoryMenu('history-customer-menu'), 120));
    custMenu.addEventListener('mousedown', (e) => e.preventDefault());
    custMenu.addEventListener('click', (e) => {
        const btn = e.target.closest('.hist-combobox-option');
        if (!btn) return;
        setHistoryCustomerById(btn.dataset.id || '');
        closeHistoryMenu('history-customer-menu');
    });
    document.getElementById('history-apply-btn').addEventListener('click', () => {
        loadHistory().catch((e) => console.error('Історія', e));
    });
    document.getElementById('history-reset-btn').addEventListener('click', () => {
        resetHistoryFiltersAndSort().catch((e) => console.error('Скидання історії', e));
    });
    dateBtn.addEventListener('click', () => {
        if (typeof dateInput.showPicker === 'function') {
            dateInput.showPicker();
        } else {
            dateInput.focus();
            dateInput.click();
        }
    });
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.hist-combobox')) {
            closeHistoryMenu('history-device-menu');
            closeHistoryMenu('history-customer-menu');
        }
    });

    loadHistoryMeta()
        .then(() => loadHistory())
        .catch((e) => console.error('Метадані історії', e));
}

async function fetchJson(url, options = {}) {
    const response = await fetch(url, { credentials: 'same-origin', ...options });
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
}

async function refreshSearchTrackersButtonState() {
    const btn = document.getElementById('toggle-search-trackers-btn');
    const data = await fetchJson('/dashboard/settings/search-new-trackers');
    if (data.enabled) {
        btn.textContent = 'Пошук трекерів: УВІМК';
        btn.classList.remove('btn-stop');
        btn.classList.add('btn-start');
    } else {
        btn.textContent = 'Пошук трекерів: ВИМК';
        btn.classList.remove('btn-start');
        btn.classList.add('btn-stop');
    }
}

async function toggleSearchTrackersMode() {
    await fetchJson('/dashboard/settings/search-new-trackers/toggle', { method: 'POST' });
    await refreshSearchTrackersButtonState();
}

async function loadRentalOptions() {
    const users = await fetchJson('/dashboard/users');
    const trackers = await fetchJson('/dashboard/trackers');

    const userSelect = document.getElementById('rent-user-select');
    const trackerSelect = document.getElementById('rent-tracker-select');

    userSelect.innerHTML = users
        .map((u) => `<option value="${u.id}">${u.last_name} ${u.first_name} (ID: ${u.id})</option>`)
        .join('');

    trackerSelect.innerHTML = trackers
        .map((t) => `<option value="${t.device_id}">${t.name} (ID: ${t.device_id})</option>`)
        .join('');
}

function setRentActionButtonState(isActive) {
    const btn = document.getElementById('rent-action-btn');
    const status = document.getElementById('rent-status-text');
    rentPairIsActive = isActive;
    if (isActive) {
        btn.textContent = 'Завершити оренду';
        btn.classList.remove('btn-start');
        btn.classList.add('btn-stop');
        status.textContent = 'Статус пари: Оренда активна';
    } else {
        btn.textContent = 'Почати оренду';
        btn.classList.remove('btn-stop');
        btn.classList.add('btn-start');
        status.textContent = 'Статус пари: Оренда неактивна';
    }
}

async function refreshPairRentalStatus() {
    const userSelect = document.getElementById('rent-user-select');
    const trackerSelect = document.getElementById('rent-tracker-select');
    const customerId = Number(userSelect.value);
    const deviceId = Number(trackerSelect.value);
    if (!customerId || !deviceId) {
        setRentActionButtonState(false);
        return;
    }
    const status = await fetchJson(`/dashboard/rentals/status?customer_id=${customerId}&device_id=${deviceId}`);
    setRentActionButtonState(Boolean(status.active));
}

async function refreshTrackerAvailability() {
    const userSelect = document.getElementById('rent-user-select');
    const trackerSelect = document.getElementById('rent-tracker-select');
    const customerId = Number(userSelect.value);
    const deviceId = Number(trackerSelect.value);

    if (!deviceId) {
        Array.from(userSelect.options).forEach((opt) => { opt.disabled = false; });
        await refreshPairRentalStatus();
        return;
    }

    const active = await fetchJson(`/dashboard/rentals/active-customer?device_id=${deviceId}`);
    const activeCustomerId = active.active_customer_id;

    if (activeCustomerId === null) {
        Array.from(userSelect.options).forEach((opt) => { opt.disabled = false; });
        await refreshPairRentalStatus();
        return;
    }

    const activeIdNum = Number(activeCustomerId);

    Array.from(userSelect.options).forEach((opt) => {
        const optId = Number(opt.value);
        opt.disabled = optId !== activeIdNum;
    });

    if (customerId !== activeIdNum) {
        userSelect.value = String(activeIdNum);
    }

    await refreshPairRentalStatus();
}

async function loadTrackersForNameModal() {
    const trackers = await fetchJson('/dashboard/trackers');
    trackersForNameModalCache = trackers;
    const trackerSelect = document.getElementById('tracker-name-select');
    trackerSelect.innerHTML = trackers
        .map((t) => `<option value="${t.device_id}">${t.name} (ID: ${t.device_id})</option>`)
        .join('');

    if (trackers.length > 0) {
        const first = trackers[0];
        trackerSelect.value = String(first.device_id);
        syncTrackerNameInputFromSelect();
    }
}

function syncTrackerNameInputFromSelect() {
    const trackerSelect = document.getElementById('tracker-name-select');
    const deviceId = Number(trackerSelect.value);
    const current = trackersForNameModalCache.find((t) => Number(t.device_id) === deviceId);
    const input = document.getElementById('tracker-name-input');
    const factorInput = document.getElementById('tracker-factor-input');
    input.value = current && current.name ? current.name : '';
    factorInput.value = current && current.correction_factor ? String(current.correction_factor) : '1';
}

function closeTrackerNameModal() {
    document.getElementById('tracker-name-modal-overlay').classList.remove('open');
}

function toggleTrackerNameModal() {
    const overlay = document.getElementById('tracker-name-modal-overlay');
    if (overlay.classList.contains('open')) {
        closeTrackerNameModal();
        return;
    }
    openTrackerNameModal().catch((e) => console.error('Не вдалося відкрити модалку редагування трекера', e));
}

async function openTrackerNameModal() {
    const overlay = document.getElementById('tracker-name-modal-overlay');
    overlay.classList.add('open');
    await refreshSearchTrackersButtonState();
    await loadTrackersForNameModal();
}

async function saveTrackerNameFromModal() {
    const trackerSelect = document.getElementById('tracker-name-select');
    const deviceId = Number(trackerSelect.value);
    const newNameRaw = document.getElementById('tracker-name-input').value;
    const trimmed = String(newNameRaw || '').trim();
    const factorRaw = document.getElementById('tracker-factor-input').value;
    const correctionFactor = Number(factorRaw);

    if (!deviceId) return;
    if (!trimmed) {
        alert('Назва не може бути порожньою.');
        return;
    }
    if (!Number.isFinite(correctionFactor) || correctionFactor <= 0) {
        alert('Коефіцієнт має бути числом більше 0.');
        return;
    }

    await fetchJson(`/dashboard/trackers/${deviceId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: trimmed, correction_factor: correctionFactor })
    });

    await loadRentalOptions();
    await loadTrackersForNameModal();
    loadHistoryMeta()
        .then(() => renderHistoryDeviceMenu())
        .catch((e) => console.error('Оновлення списку трекерів для історії', e));
    closeTrackerNameModal();
}

async function loadUsersForUsersModal() {
    const users = await fetchJson('/dashboard/users/full');
    usersForUsersModalCache = users;

    const select = document.getElementById('users-modal-select');
    const currentValue = select.value;

    select.innerHTML = '<option value="">Новий користувач</option>' + users
        .map((u) => `<option value="${u.id}">${u.last_name} ${u.first_name} (ID: ${u.id})</option>`)
        .join('');

    if (currentValue && users.some((u) => String(u.id) === String(currentValue))) {
        select.value = currentValue;
    } else {
        select.value = '';
    }

    syncUserFormFromSelection();
}

function resetUsersForm() {
    document.getElementById('users-modal-first-name').value = '';
    document.getElementById('users-modal-last-name').value = '';
    document.getElementById('users-modal-middle-name').value = '';
    document.getElementById('users-modal-age').value = '';
    document.getElementById('users-modal-height').value = '';
    document.getElementById('users-modal-weight').value = '';
    document.getElementById('users-modal-sex').value = 'male';
}

function syncUserFormFromSelection() {
    const select = document.getElementById('users-modal-select');
    const userId = select.value;
    if (!userId) {
        resetUsersForm();
        return;
    }

    const user = usersForUsersModalCache.find((u) => String(u.id) === String(userId));
    if (!user) {
        resetUsersForm();
        return;
    }

    document.getElementById('users-modal-first-name').value = user.first_name || '';
    document.getElementById('users-modal-last-name').value = user.last_name || '';
    document.getElementById('users-modal-middle-name').value = user.middle_name || '';
    document.getElementById('users-modal-age').value = user.age ?? '';
    document.getElementById('users-modal-height').value = user.height ?? '';
    document.getElementById('users-modal-weight').value = user.weight ?? '';
    document.getElementById('users-modal-sex').value = user.sex || 'male';
}

function closeUsersModal() {
    document.getElementById('users-modal-overlay').classList.remove('open');
}

function toggleUsersModal() {
    const overlay = document.getElementById('users-modal-overlay');
    if (overlay.classList.contains('open')) {
        closeUsersModal();
        return;
    }
    openUsersModal().catch((e) => console.error('Не вдалося відкрити модалку користувачів', e));
}

async function openUsersModal() {
    const overlay = document.getElementById('users-modal-overlay');
    overlay.classList.add('open');
    await loadUsersForUsersModal();
}

async function saveUsersFromModal() {
    const select = document.getElementById('users-modal-select');
    const userIdRaw = select.value;
    const userId = userIdRaw ? Number(userIdRaw) : null;

    const firstName = document.getElementById('users-modal-first-name').value.trim();
    const lastName = document.getElementById('users-modal-last-name').value.trim();
    const middleNameRaw = document.getElementById('users-modal-middle-name').value.trim();
    const middleName = middleNameRaw ? middleNameRaw : null;

    const age = parseInt(document.getElementById('users-modal-age').value, 10);
    const height = parseInt(document.getElementById('users-modal-height').value, 10);
    const weight = parseInt(document.getElementById('users-modal-weight').value, 10);
    const sex = document.getElementById('users-modal-sex').value;

    if (!firstName || !lastName || !Number.isFinite(age) || !Number.isFinite(height) || !Number.isFinite(weight) || !sex) {
        alert('Заповніть обов’язкові поля: ім’я, прізвище, вік, зріст, вага, стать.');
        return;
    }

    const payload = {
        first_name: firstName,
        last_name: lastName,
        middle_name: middleName,
        age: age,
        height: height,
        weight: weight,
        sex: sex
    };

    if (userId) {
        await fetchJson(`/dashboard/users/${userId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
    } else {
        await fetchJson('/dashboard/users', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
    }

    closeUsersModal();
    await loadRentalOptions();
    loadHistoryMeta()
        .then(() => renderHistoryUserMenu())
        .catch((e) => console.error('Оновлення списку користувачів для історії', e));
}

async function onRentActionClick() {
    const userSelect = document.getElementById('rent-user-select');
    const trackerSelect = document.getElementById('rent-tracker-select');
    const customerId = Number(userSelect.value);
    const deviceId = Number(trackerSelect.value);
    if (!customerId || !deviceId) return;

    if (rentPairIsActive) {
        await fetchJson(`/dashboard/rentals/stop?customer_id=${customerId}&device_id=${deviceId}`, { method: 'POST' });
    } else {
        await fetchJson('/dashboard/rentals/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ customer_id: customerId, device_id: deviceId })
        });
    }
    await refreshTrackerAvailability();
    await refreshActivePairsCount();
}

async function openRentModal() {
    const overlay = document.getElementById('rent-modal-overlay');
    overlay.classList.add('open');
    if (!rentalDataLoaded) {
        await loadRentalOptions();
        rentalDataLoaded = true;
    }
    await refreshTrackerAvailability();
}

function closeRentModal() {
    document.getElementById('rent-modal-overlay').classList.remove('open');
}

function initRentModalHandlers() {
    document.getElementById('open-rent-modal-btn').addEventListener('click', () => {
        openRentModal().catch((e) => console.error('Не вдалося відкрити модалку оренди', e));
    });
    document.getElementById('rent-modal-close-btn').addEventListener('click', closeRentModal);
    document.getElementById('rent-action-btn').addEventListener('click', () => {
        onRentActionClick().catch((e) => console.error('Помилка керування орендою', e));
    });
    document.getElementById('rent-user-select').addEventListener('change', () => {
        refreshTrackerAvailability().catch((e) => console.error('Помилка оновлення доступності трекера', e));
    });
    document.getElementById('rent-tracker-select').addEventListener('change', () => {
        refreshTrackerAvailability().catch((e) => console.error('Помилка оновлення доступності трекера', e));
    });
    document.getElementById('rent-modal-overlay').addEventListener('click', (e) => {
        if (e.target.id === 'rent-modal-overlay') closeRentModal();
    });
    document.getElementById('toggle-search-trackers-btn').addEventListener('click', () => {
        toggleSearchTrackersMode().catch((e) => console.error('Помилка перемикання пошуку трекерів', e));
    });

    document.getElementById('open-edit-tracker-name-modal-btn').addEventListener('click', () => {
        toggleTrackerNameModal();
    });
    document.getElementById('tracker-name-modal-close-btn').addEventListener('click', closeTrackerNameModal);
    document.getElementById('tracker-name-save-btn').addEventListener('click', () => {
        saveTrackerNameFromModal().catch((e) => console.error('Помилка збереження назви трекера', e));
    });
    document.getElementById('tracker-name-select').addEventListener('change', () => {
        syncTrackerNameInputFromSelect();
    });

    document.getElementById('open-users-modal-btn').addEventListener('click', () => {
        toggleUsersModal();
    });
    document.getElementById('users-modal-close-btn').addEventListener('click', closeUsersModal);
    document.getElementById('users-modal-save-btn').addEventListener('click', () => {
        saveUsersFromModal().catch((e) => console.error('Помилка збереження користувача', e));
    });
    document.getElementById('users-modal-select').addEventListener('change', () => {
        syncUserFormFromSelection();
    });
    document.getElementById('users-modal-overlay').addEventListener('click', (e) => {
        if (e.target.id === 'users-modal-overlay') closeUsersModal();
    });

    document.getElementById('tracker-name-modal-overlay').addEventListener('click', (e) => {
        if (e.target.id === 'tracker-name-modal-overlay') closeTrackerNameModal();
    });
}

document.addEventListener('DOMContentLoaded', () => {
    initRentModalHandlers();
    initHistorySection();
    refreshActivePairsCount().catch((e) => console.error('Не вдалося отримати кількість активних пар', e));
    setInterval(() => {
        refreshActivePairsCount().catch((e) => console.error('Не вдалося оновити кількість активних пар', e));
    }, 5000);
    refreshSearchTrackersButtonState().catch((e) => console.error('Не вдалося отримати стан пошуку трекерів', e));
});
