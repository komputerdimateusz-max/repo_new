const CART_KEY = 'cart_v1';

const state = {
  settings: null,
  companies: [],
  menu: { categories: [], active_category: null, items: [] },
  isClosed: false,
  cart: loadCart(),
};

function loadCart() {
  try {
    const parsed = JSON.parse(localStorage.getItem(CART_KEY) || '{}');
    return {
      company_id: parsed.company_id || '',
      items: parsed.items || {},
      notes: parsed.notes || '',
      payment_method: parsed.payment_method || '',
    };
  } catch (_) {
    return { company_id: '', items: {}, notes: '', payment_method: '' };
  }
}

function saveCart() {
  localStorage.setItem(CART_KEY, JSON.stringify(state.cart));
}

function formatMoney(value) {
  return `${Number(value).toFixed(2).replace('.', ',')} zł`;
}

function isCartEmpty() {
  return Object.keys(state.cart.items).length === 0;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw { status: response.status, detail: payload.detail || 'Request failed.' };
  }
  return response.json();
}

function computeClosed(settings) {
  const now = new Date(settings.now_server);
  const [h, m] = settings.cut_off_time.split(':').map(Number);
  const cutoff = new Date(now);
  cutoff.setHours(h, m, 0, 0);
  return now > cutoff;
}

function menuCardTemplate(item) {
  const inCartQty = state.cart.items[item.id]?.qty || 0;
  const disabled = state.isClosed ? 'disabled' : '';
  return `
    <article class="menu-card" data-menu-card data-menu-item-id="${item.id}">
      <img class="menu-thumb" src="${item.image_url || '/static/placeholder_food.svg'}" alt="Zdjęcie dania ${item.name}" loading="lazy" />
      <div class="menu-card-content">
        <div class="menu-copy">
          <h3>${item.name}</h3>
          <p>${item.description || ''}</p>
        </div>
        <div class="menu-meta">
          ${item.badge ? `<span class="badge standard">${item.badge}</span>` : ''}
          <div class="price-row">
            <span class="price">${formatMoney(item.price)}</span>
            <button type="button" class="add-btn" data-add-btn ${inCartQty > 0 ? 'hidden' : ''} ${disabled}>Dodaj</button>
            <div class="qty-stepper" data-qty-control ${inCartQty === 0 ? 'hidden' : ''}>
              <button type="button" aria-label="Zmniejsz ilość" data-action="decrease" ${disabled}>−</button>
              <span data-qty>${inCartQty}</span>
              <button type="button" aria-label="Zwiększ ilość" data-action="increase" ${disabled}>+</button>
            </div>
          </div>
        </div>
      </div>
    </article>`;
}

function renderTabs() {
  const container = document.querySelector('[data-category-tabs]');
  container.innerHTML = state.menu.categories.map((category) => {
    const active = category === state.menu.active_category ? 'active' : '';
    return `<button class="tab ${active}" type="button" data-category="${category}">${category}</button>`;
  }).join('');

  container.querySelectorAll('[data-category]').forEach((tab) => {
    tab.addEventListener('click', async () => {
      await loadMenu(tab.dataset.category);
    });
  });
}

function renderMenu() {
  const grid = document.querySelector('[data-menu-grid]');
  grid.innerHTML = state.menu.items.map(menuCardTemplate).join('');

  grid.querySelectorAll('[data-menu-card]').forEach((card) => {
    const itemId = card.dataset.menuItemId;
    const addBtn = card.querySelector('[data-add-btn]');
    const qtyControl = card.querySelector('[data-qty-control]');
    const qtyEl = card.querySelector('[data-qty]');
    const menuItem = state.menu.items.find((x) => String(x.id) === itemId);
    if (!menuItem || !qtyEl) return;

    const setQty = (qty) => {
      const next = Math.max(0, qty);
      if (next === 0) {
        delete state.cart.items[itemId];
      } else {
        state.cart.items[itemId] = { qty: next, name: menuItem.name, price: Number(menuItem.price) };
      }
      saveCart();
      renderMenu();
      renderCart();
    };

    addBtn?.addEventListener('click', () => setQty(1));
    qtyControl?.addEventListener('click', (event) => {
      const target = event.target;
      if (!(target instanceof HTMLButtonElement)) return;
      const current = Number(qtyEl.textContent) || 0;
      if (target.dataset.action === 'increase') setQty(current + 1);
      if (target.dataset.action === 'decrease') setQty(current - 1);
    });
  });
}

function renderCart() {
  const list = document.querySelector('[data-cart-list]');
  const subtotal = Object.values(state.cart.items).reduce((sum, item) => sum + item.qty * item.price, 0);
  list.innerHTML = Object.values(state.cart.items).map((item) =>
    `<li><div><strong>${item.name}</strong><small>${item.qty} × ${formatMoney(item.price)}</small></div></li>`
  ).join('');

  document.querySelector('[data-summary-subtotal]').textContent = formatMoney(subtotal);
  const deliveryFee = Number(state.settings?.delivery_fee || 0);
  document.querySelector('[data-summary-delivery]').textContent = formatMoney(deliveryFee);
  document.querySelector('[data-summary-window]').textContent = `${state.settings?.delivery_window_start || '--:--'}–${state.settings?.delivery_window_end || '--:--'}`;
  document.querySelector('[data-summary-total]').textContent = formatMoney(subtotal + deliveryFee);

  const checkoutBtn = document.querySelector('[data-checkout-btn]');
  checkoutBtn.disabled = isCartEmpty() || state.isClosed;
}

function renderCompanies() {
  const select = document.querySelector('[data-company-select]');
  select.innerHTML = '<option value="">Wybierz firmę</option>' + state.companies.map((company) =>
    `<option value="${company.id}">${company.name}</option>`
  ).join('');
  if (state.cart.company_id) select.value = String(state.cart.company_id);
  select.addEventListener('change', () => {
    state.cart.company_id = select.value ? Number(select.value) : '';
    saveCart();
  });
}

function renderSettings() {
  document.querySelector('[data-cutoff-time]').textContent = state.settings.cut_off_time;
  document.querySelector('[data-cutoff-banner]').hidden = !state.isClosed;
}

function wireSidebarInputs() {
  const notes = document.querySelector('[data-cart-notes]');
  notes.value = state.cart.notes;
  notes.addEventListener('input', () => {
    state.cart.notes = notes.value;
    saveCart();
  });

  document.querySelectorAll('[data-payment-method]').forEach((btn) => {
    btn.classList.toggle('blik', btn.dataset.paymentMethod === state.cart.payment_method);
    btn.addEventListener('click', () => {
      state.cart.payment_method = btn.dataset.paymentMethod;
      saveCart();
      document.querySelectorAll('[data-payment-method]').forEach((innerBtn) => {
        innerBtn.classList.toggle('blik', innerBtn.dataset.paymentMethod === state.cart.payment_method);
      });
    });
  });
}

function setMessage(text, isError = false) {
  const el = document.querySelector('[data-inline-message]');
  el.hidden = !text;
  el.textContent = text;
  el.style.color = isError ? '#b42318' : '#0f5132';
}

async function submitOrder() {
  const payload = {
    customer_email: 'demo@user.com',
    company_id: state.cart.company_id,
    notes: state.cart.notes,
    payment_method: state.cart.payment_method,
    items: Object.entries(state.cart.items).map(([menu_item_id, item]) => ({ menu_item_id: Number(menu_item_id), qty: item.qty })),
  };

  if (!payload.company_id || !payload.payment_method || payload.items.length === 0) {
    setMessage('Wybierz firmę, płatność i co najmniej jedną pozycję.', true);
    return;
  }

  try {
    const response = await fetchJson('/api/v1/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    setMessage(`Zamówienie #${response.order_id} przyjęte.`);
    state.cart = { company_id: state.cart.company_id, items: {}, notes: '', payment_method: '' };
    saveCart();
    document.querySelector('[data-cart-notes]').value = '';
    renderMenu();
    renderCart();
    wireSidebarInputs();
  } catch (error) {
    if (error.status === 403) {
      state.isClosed = true;
      renderSettings();
      renderMenu();
      renderCart();
      setMessage('Zamówienia na dziś są zamknięte.', true);
      return;
    }
    setMessage(error.detail || 'Nie udało się złożyć zamówienia.', true);
  }
}

async function loadMenu(category = '') {
  const suffix = category ? `?category=${encodeURIComponent(category)}` : '';
  state.menu = await fetchJson(`/api/v1/menu/today${suffix}`);
  if (!state.menu.active_category && state.menu.categories.length > 0) {
    state.menu.active_category = state.menu.categories[0];
  }
  renderTabs();
  renderMenu();
}

async function init() {
  state.settings = await fetchJson('/api/v1/settings');
  state.companies = await fetchJson('/api/v1/companies');
  state.isClosed = computeClosed(state.settings);

  renderSettings();
  renderCompanies();
  wireSidebarInputs();
  await loadMenu();
  renderCart();

  document.querySelector('[data-checkout-btn]').addEventListener('click', submitOrder);
}

init().catch(() => setMessage('Nie udało się załadować danych.', true));
