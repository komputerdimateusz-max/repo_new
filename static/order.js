document.querySelectorAll('[data-qty-control]').forEach((control) => {
  const qtyElement = control.querySelector('[data-qty]');
  control.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) {
      return;
    }

    const action = target.dataset.action;
    const currentQty = Number(qtyElement.textContent) || 0;

    if (action === 'increase') {
      qtyElement.textContent = String(currentQty + 1);
      return;
    }

    if (action === 'decrease') {
      qtyElement.textContent = String(Math.max(0, currentQty - 1));
    }
  });
});
