document.querySelectorAll('[data-menu-card]').forEach((card) => {
  const addButton = card.querySelector('[data-add-btn]');
  const qtyControl = card.querySelector('[data-qty-control]');

  if (!(addButton instanceof HTMLButtonElement) || !(qtyControl instanceof HTMLElement)) {
    return;
  }

  const qtyElement = qtyControl.querySelector('[data-qty]');
  if (!(qtyElement instanceof HTMLElement)) {
    return;
  }

  const setQty = (nextValue) => {
    const qty = Math.max(0, nextValue);
    qtyElement.textContent = String(qty);

    if (qty === 0) {
      qtyControl.hidden = true;
      addButton.hidden = false;
      return;
    }

    qtyControl.hidden = false;
    addButton.hidden = true;
  };

  addButton.addEventListener('click', () => {
    setQty(1);
  });

  qtyControl.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) {
      return;
    }

    const action = target.dataset.action;
    const currentQty = Number(qtyElement.textContent) || 0;

    if (action === 'increase') {
      setQty(currentQty + 1);
      return;
    }

    if (action === 'decrease') {
      setQty(currentQty - 1);
    }
  });
});
