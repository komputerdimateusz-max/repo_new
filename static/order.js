const CART_KEY = 'cart_v1';

const state = {
  settings: null,
  companies: [],
  me: null,
  menu: { categories: [], active_category: null, items: [] },
  cart: loadCart(),
};

function loadCart() {
  try {
    const parsed = JSON.parse(localStorage.getItem(CART_KEY) || '{}');
    return {
      items: parsed.items || {},
      notes: parsed.notes || '',
      payment_method: parsed.payment_method || '',
    };
  } catch (_error) {
    return { items: {}, notes: '', payment_method: '' };
  }
}

function saveCart() {
  localStorage.setItem(CART_KEY, JSON.stringify(state.cart));
  console.log('[CART] state', state.cart);
}

function clearCart() {
  localStorage.removeItem(CART_KEY);
  state.cart = { items: {}, notes: '', payment_method: '' };
}

function formatMoney(value) {
  return `${Number(value).toFixed(2).replace('.', ',')} zł`;
}

function fetchJson(url, options = {}) {
  return fetch(url, options).then(async (response) => {
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw { status: response.status, detail: payload.detail || 'Request failed' };
    }
    return response.json();
  });
}

function setMessage(text, isError = false) {
  const el = document.querySelector('[data-inline-message]');
  el.hidden = !text;
  el.textContent = text;
  el.style.color = isError ? '#b42318' : '#0f5132';
}

function getQty(itemId) {
  return state.cart.items[String(itemId)]?.qty || 0;
}

function setQty(item, qty) {
  const key = String(item.id);
  const next = Math.max(0, qty);
  if (next === 0) {
    delete state.cart.items[key];
  } else {
    state.cart.items[key] = {
      id: item.id,
      name: item.name,
      price: Number(item.price),
      qty: next,
    };
  }
  saveCart();
  renderMenu();
  renderCart();
}

function renderTabs() {
  const host = document.querySelector('[data-category-tabs]');
  host.innerHTML = '';
  for (const category of state.menu.categories || []) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = category;
    button.className = state.menu.active_category === category ? 'category-tab active' : 'category-tab';
    button.addEventListener('click', () => {
      loadMenu(category).catch(() => setMessage('Nie udało się załadować menu.', true));
    });
    host.appendChild(button);
  }
}

function renderMenu() {
  const grid = document.querySelector('[data-menu-grid]');
  grid.innerHTML = '';

  for (const item of state.menu.items) {
    const qty = getQty(item.id);
    const article = document.createElement('article');
    article.className = 'menu-card';
    article.innerHTML = `
      <img class="menu-thumb" src="${item.image_url || '/static/placeholder_food.svg'}" alt="${item.name}" loading="lazy" />
      <div class="menu-card-content">
        <div class="menu-copy">
          <h3>${item.name}</h3>
          <p>${item.description || ''}</p>
        </div>
        <div class="menu-meta">
          ${item.badge ? `<span class="badge standard">${item.badge}</span>` : ''}
          <div class="price-row">
            <span class="price">${formatMoney(item.price)}</span>
            <button type="button" data-add-btn>Dodaj</button>
          </div>
          <div data-stepper ${qty > 0 ? '' : 'hidden'}>
            <button type="button" data-dec>-</button>
            <span data-qty>${qty}</span>
            <button type="button" data-inc>+</button>
          </div>
        </div>
      </div>
    `;

    article.querySelector('[data-add-btn]')?.addEventListener('click', () => {
      console.log('[CART] add', item.id);
      setQty(item, getQty(item.id) + 1);
    });
    article.querySelector('[data-inc]')?.addEventListener('click', () => setQty(item, getQty(item.id) + 1));
    article.querySelector('[data-dec]')?.addEventListener('click', () => setQty(item, getQty(item.id) - 1));

    grid.appendChild(article);
  }
}

function renderCart() {
  const list = document.querySelector('[data-cart-list]');
  const entries = Object.values(state.cart.items);

  list.innerHTML = entries
    .map(
      (item) => `
      <li>
        <div><strong>${item.name}</strong><small>${item.qty} × ${formatMoney(item.price)}</small></div>
        <div>
          <button type="button" data-cart-dec="${item.id}">-</button>
          <button type="button" data-cart-inc="${item.id}">+</button>
        </div>
      </li>`
    )
    .join('');

  for (const button of list.querySelectorAll('[data-cart-dec]')) {
    button.addEventListener('click', () => {
      const menuItem = state.menu.items.find((it) => String(it.id) === button.dataset.cartDec);
      if (menuItem) setQty(menuItem, getQty(menuItem.id) - 1);
    });
  }
  for (const button of list.querySelectorAll('[data-cart-inc]')) {
    button.addEventListener('click', () => {
      const menuItem = state.menu.items.find((it) => String(it.id) === button.dataset.cartInc);
      if (menuItem) setQty(menuItem, getQty(menuItem.id) + 1);
    });
  }

  const subtotal = entries.reduce((sum, item) => sum + item.qty * item.price, 0);
  const delivery = Number(state.settings?.delivery_fee || 0);

  document.querySelector('[data-summary-subtotal]').textContent = formatMoney(subtotal);
  document.querySelector('[data-summary-delivery]').textContent = formatMoney(delivery);
  document.querySelector('[data-summary-window]').textContent = `${state.settings?.delivery_window_start || '--:--'}–${state.settings?.delivery_window_end || '--:--'}`;
  document.querySelector('[data-summary-total]').textContent = formatMoney(subtotal + delivery);

  document.querySelector('[data-company-required-banner]').hidden = true;
  document.querySelector('[data-checkout-btn]').disabled = entries.length === 0;
}

function wireSidebarInputs() {
  const notes = document.querySelector('[data-cart-notes]');
  notes.value = state.cart.notes;
  notes.addEventListener('input', () => {
    state.cart.notes = notes.value;
    saveCart();
  });

  for (const button of document.querySelectorAll('[data-payment-method]')) {
    button.classList.toggle('blik', button.dataset.paymentMethod === state.cart.payment_method);
    button.addEventListener('click', () => {
      state.cart.payment_method = button.dataset.paymentMethod;
      saveCart();
      for (const inner of document.querySelectorAll('[data-payment-method]')) {
        inner.classList.toggle('blik', inner.dataset.paymentMethod === state.cart.payment_method);
      }
    });
  }
}

async function loadMenu(category = '') {
  const suffix = category ? `?category=${encodeURIComponent(category)}` : '';
  const payload = await fetchJson(`/api/v1/menu/today${suffix}`);
  state.menu = payload;
  if (!state.menu.active_category && state.menu.categories.length > 0) {
    state.menu.active_category = state.menu.categories[0];
  }
  renderTabs();
  renderMenu();
}

async function submitOrder() {
  const payload = {
    notes: state.cart.notes,
    payment_method: state.cart.payment_method,
    items: Object.values(state.cart.items).map((item) => ({ menu_item_id: item.id, qty: item.qty })),
  };

  if (!payload.payment_method) {
    setMessage('Wybierz metodę płatności.', true);
    return;
  }

  try {
    const response = await fetchJson('/api/v1/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    setMessage(`Zamówienie przyjęte #${response.order_id}`);
    clearCart();
    renderMenu();
    renderCart();
    wireSidebarInputs();
  } catch (error) {
    setMessage(error.detail || 'Nie udało się złożyć zamówienia.', true);
  }
}

async function init() {
  state.settings = await fetchJson('/api/v1/settings');
  state.companies = await fetchJson('/api/v1/companies');
  state.me = await fetchJson('/api/v1/me');

  document.querySelector('[data-cutoff-time]').textContent = state.settings.cut_off_time;
  document.querySelector('[data-cutoff-banner]').hidden = true;

  wireSidebarInputs();
  await loadMenu();
  renderCart();

  document.querySelector('[data-checkout-btn]').addEventListener('click', submitOrder);
}

document.addEventListener('DOMContentLoaded', () => {
  init().catch(() => setMessage('Nie udało się załadować danych.', true));
});
