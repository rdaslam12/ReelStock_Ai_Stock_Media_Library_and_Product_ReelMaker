/* ==========================================================================
   ReelStock — Wallet & Download Basket JS
   Handles: Add-to-basket AJAX, navbar badge updates, toast notifications.
   ========================================================================== */
(function () {
  'use strict';

  // ── Toast helper ────────────────────────────────────────────────────────
  function showToast(message, kind) {
    kind = kind || 'success';
    var container = document.getElementById('rs-toast-container');
    if (!container) return;

    var icons = { success: '✅', warning: '⚠️', error: '❌', info: 'ℹ️' };
    var toast = document.createElement('div');
    toast.className = 'rs-toast ' + kind;
    toast.innerHTML =
      '<span class="rs-toast-icon">' + (icons[kind] || icons.info) + '</span>' +
      '<span class="rs-toast-msg"></span>';
    toast.querySelector('.rs-toast-msg').textContent = message;
    container.appendChild(toast);

    setTimeout(function () {
      toast.classList.add('fade-out');
      setTimeout(function () {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 320);
    }, 2800);
  }
  window.rsToast = showToast;

  // ── Update navbar badge + balance pill ──────────────────────────────────
  function updateNavbar(count, balance) {
    var badge = document.getElementById('navBasketCount');
    if (badge && typeof count === 'number') {
      badge.textContent = count;
      if (count > 0) {
        badge.classList.remove('is-empty');
      } else {
        badge.classList.add('is-empty');
      }
      var btn = badge.closest('.basket-btn');
      if (btn) {
        btn.classList.remove('basket-bump');
        // Force reflow so the animation can replay
        void btn.offsetWidth;
        btn.classList.add('basket-bump');
      }
    }
    var balanceEl = document.getElementById('navCoinBalance');
    if (balanceEl && typeof balance === 'number') {
      balanceEl.textContent = balance;
      var pill = balanceEl.closest('.coin-pill');
      if (pill) {
        pill.classList.remove('coin-pill-bump');
        void pill.offsetWidth;
        pill.classList.add('coin-pill-bump');
      }
    }
  }
  window.rsUpdateNavbar = updateNavbar;

  // ── Open the login modal ────────────────────────────────────────────────
  function openLoginModal() {
    var modalEl = document.getElementById('loginModal');
    if (modalEl && window.bootstrap) {
      var modal = window.bootstrap.Modal.getOrCreateInstance(modalEl);
      modal.show();
    } else {
      window.location.href = (window.RS && window.RS.urls.login) || '/login/';
    }
  }

  // ── Add to basket (AJAX) ────────────────────────────────────────────────
  function addToBasket(button) {
    if (!window.RS) return;
    if (!window.RS.isAuthenticated) {
      showToast('Please log in to add items to your basket.', 'warning');
      openLoginModal();
      return;
    }
    if (button.classList.contains('btn-basket-loading')) return;
    if (button.classList.contains('is-in-basket')) return;

    var assetType = button.getAttribute('data-asset-type');
    var assetId   = button.getAttribute('data-asset-id');
    if (!assetType || !assetId) return;

    var originalLabel = button.innerHTML;
    button.classList.add('btn-basket-loading');
    button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';

    fetch(window.RS.urls.basketAdd, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': window.RS.csrfToken,
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: JSON.stringify({ asset_type: assetType, asset_id: parseInt(assetId, 10) }),
    })
      .then(function (r) {
        return r.json().then(function (data) { return { ok: r.ok, data: data }; });
      })
      .then(function (result) {
        button.classList.remove('btn-basket-loading');
        if (!result.ok || !result.data.ok) {
          button.innerHTML = originalLabel;
          showToast(result.data && result.data.message || 'Could not add to basket.', 'error');
          return;
        }
        var data = result.data;
        // Mark all matching buttons as "in basket"
        var matching = document.querySelectorAll(
          '.btn-basket[data-asset-type="' + assetType + '"][data-asset-id="' + assetId + '"]'
        );
        matching.forEach(function (b) {
          b.classList.add('is-in-basket');
          b.innerHTML = '✓ In Basket';
          b.setAttribute('disabled', 'disabled');
        });
        updateNavbar(data.count, data.balance);
        showToast(data.message || 'Added!', data.created ? 'success' : 'info');
      })
      .catch(function () {
        button.classList.remove('btn-basket-loading');
        button.innerHTML = originalLabel;
        showToast('Network error. Please try again.', 'error');
      });
  }

  // ── Bind every Add-to-basket button on the page ─────────────────────────
  function bindBasketButtons() {
    document.querySelectorAll('.btn-basket').forEach(function (btn) {
      // Avoid double-binding
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        addToBasket(btn);
      });
    });
  }

  document.addEventListener('DOMContentLoaded', bindBasketButtons);
  // Also expose for any dynamically-added buttons (Generate page, etc.)
  window.rsBindBasketButtons = bindBasketButtons;
})();
