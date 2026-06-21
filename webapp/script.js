(function () {
  'use strict';

  var tg = window.Telegram && window.Telegram.WebApp;

  function checkIsWebApp() {
    return tg && tg.platform && tg.platform !== 'unknown';
  }

  if (tg) {
    tg.ready();
    if (checkIsWebApp()) tg.expand();
  }

  var plansEl = document.getElementById('plansGrid');
  var buyBtn = document.getElementById('heroBuyBtn');
  var scrollBtn = document.getElementById('heroScrollBtn');
  var progressBar = document.getElementById('progressBar');
  var footerYear = document.getElementById('footerYear');

  if (footerYear) {
    footerYear.textContent = String(new Date().getFullYear());
  }

  function debounce(func, wait) {
    var timeout;
    return function() {
      var context = this, args = arguments;
      clearTimeout(timeout);
      timeout = setTimeout(function() { func.apply(context, args); }, wait);
    };
  }

  var rafId = null;
  function updateProgress() {
    if (rafId) return;
    rafId = requestAnimationFrame(function() {
      var scrollTop = window.scrollY || document.documentElement.scrollTop;
      var docHeight = document.documentElement.scrollHeight - window.innerHeight;
      var progress = docHeight > 0 ? scrollTop / docHeight : 0;
      if (progressBar) progressBar.style.transform = 'scaleX(' + progress + ')';
      rafId = null;
    });
  }
  
  window.addEventListener('scroll', updateProgress, { passive: true });
  window.addEventListener('resize', debounce(updateProgress, 150), { passive: true });
  updateProgress();

  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
      }
    });
  }, { threshold: 0.15, rootMargin: '0px 0px -40px 0px' });

  document.querySelectorAll('[data-animate]:not([data-promo-only])').forEach(function (el) {
    observer.observe(el);
  });

  if (scrollBtn) {
    scrollBtn.addEventListener('click', function () {
      var features = document.getElementById('features');
      if (features) features.scrollIntoView({ behavior: 'smooth' });
      if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
    });
  }

  var botUsername = '';

  var discountEnabled = false;
  var discountPct = 0;

  var PLAN_META = {
    '1m': {
      tag: 'Старт',
      title: '1 месяц',
      term: '30 дней доступа',
      note: 'Короткий доступ для знакомства со скриптом.',
      benefits: ['Личный токен доступа', 'Обновления цен и таблиц']
    },
    '2m': {
      tag: 'Баланс',
      title: '2 месяца',
      term: '60 дней доступа',
      note: 'Спокойный срок для проверки связки в работе.',
      benefits: ['Выгоднее одного месяца', 'Доступ к Lua-функциям']
    },
    '3m': {
      tag: 'Популярный',
      title: '3 месяца',
      term: '90 дней доступа',
      note: 'Оптимальный вариант для регулярной работы.',
      benefits: ['Полный набор инструментов', 'Подходит для активной работы']
    },
    '6m': {
      tag: 'Выгодно',
      title: '6 месяцев',
      term: '180 дней доступа',
      note: 'Долгий доступ без частых продлений.',
      benefits: ['Максимальная выгода по сроку', 'Все будущие обновления']
    },
    'forever': {
      tag: 'Навсегда',
      title: 'Forever',
      term: 'Бессрочный доступ',
      note: 'Один платёж и доступ без ограничения срока.',
      benefits: ['Бессрочный токен', 'Все ключевые функции']
    }
  };

  function togglePromoAdvantages(enabled) {
    document.querySelectorAll('[data-promo-only]').forEach(function (el) {
      el.hidden = !enabled;
      if (enabled) observer.observe(el);
    });
  }

  function closeWebApp() {
    if (tg && typeof tg.close === 'function') {
      try { tg.close(); } catch (e) {}
    }
  }

  function redirectToBot(planCode) {
    var startParam = 'buy_' + (planCode || '');
    var url = 'https://t.me/' + (botUsername || 'TestKeyBot_bot') + '?start=' + startParam;
    window.location.href = url;
  }

  function selectPlan(plan) {
    var payload = JSON.stringify({ plan: plan.code, label: plan.label, price_rub: plan.price_rub, price_stars: plan.price_stars });
    if (checkIsWebApp()) {
      if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
      document.body.style.pointerEvents = 'none';
      try {
        if (typeof tg.sendData === 'function') {
          tg.sendData(payload);
        } else {
          tg.close();
        }
      } catch (e) {
        tg.close();
      }
    } else {
      redirectToBot(plan.code);
    }
  }

  function renderPlans(plans) {
    if (!plansEl) return;
    var fragment = document.createDocumentFragment();
    
    plans.forEach(function (plan) {
      var meta = PLAN_META[plan.code] || {
        tag: 'Тариф',
        title: plan.label,
        term: plan.description || 'Доступ к инструментам',
        note: 'Доступ к таблице, скрипту и обновлениям.',
        benefits: ['Личный токен доступа', 'Обновления цен']
      };
      var wrapper = document.createElement('div');
      wrapper.className = 'plan-card';
      wrapper.setAttribute('data-animate', '');
      if (plan.highlighted) wrapper.classList.add('plan-card--highlighted');
      wrapper.dataset.code = plan.code;

      var inner = document.createElement('div');
      inner.className = 'plan-card__inner';

      var badge = document.createElement('div');
      badge.className = 'plan-card__badge';
      badge.textContent = meta.tag;
      inner.appendChild(badge);

      var info = document.createElement('div');
      info.className = 'plan-card__info';

      var top = document.createElement('div');
      top.className = 'plan-card__top';

      var name = document.createElement('div');
      name.className = 'plan-card__name';
      name.textContent = meta.title || plan.label;
      if (discountEnabled && discountPct > 0) {
        var inlineDisc = document.createElement('span');
        inlineDisc.className = 'plan-card__discount-inline';
        inlineDisc.textContent = '-' + discountPct + '%';
        name.appendChild(inlineDisc);
      }
      top.appendChild(name);

      var term = document.createElement('div');
      term.className = 'plan-card__term';
      term.textContent = meta.term || plan.description || '';
      top.appendChild(term);
      info.appendChild(top);

      var desc = document.createElement('div');
      desc.className = 'plan-card__desc';
      desc.textContent = meta.note || plan.description || '';
      info.appendChild(desc);

      var benefits = document.createElement('ul');
      benefits.className = 'plan-card__benefits';
      (meta.benefits || []).forEach(function (text) {
        var item = document.createElement('li');
        item.textContent = text;
        benefits.appendChild(item);
      });
      info.appendChild(benefits);

      var priceWrap = document.createElement('div');
      priceWrap.className = 'plan-card__price-wrap';

      var rubBlock = document.createElement('div');
      rubBlock.className = 'plan-card__price-block';

      if (discountEnabled && discountPct > 0) {
        var discountedRub = Math.round(plan.price_rub * (100 - discountPct) / 100);
        var currentPriceRub = document.createElement('span');
        currentPriceRub.className = 'plan-card__price plan-card__price--current';
        currentPriceRub.textContent = discountedRub + ' ₽';
        rubBlock.appendChild(currentPriceRub);

        var oldPriceRub = document.createElement('span');
        oldPriceRub.className = 'plan-card__price plan-card__price--old';
        oldPriceRub.textContent = plan.price_rub + ' ₽';
        rubBlock.appendChild(oldPriceRub);
      } else {
        var priceRub = document.createElement('span');
        priceRub.className = 'plan-card__price';
        priceRub.textContent = plan.price_rub + ' ₽';
        rubBlock.appendChild(priceRub);
      }
      priceWrap.appendChild(rubBlock);

      var starsBlock = document.createElement('div');
      starsBlock.className = 'plan-card__price-block';

      if (discountEnabled && discountPct > 0) {
        var discountedStars = Math.round(plan.price_stars * (100 - discountPct) / 100);
        var currentPriceStars = document.createElement('span');
        currentPriceStars.className = 'plan-card__price plan-card__price--stars plan-card__price--current';
        currentPriceStars.textContent = discountedStars + ' ⭐';
        starsBlock.appendChild(currentPriceStars);

        var oldPriceStars = document.createElement('span');
        oldPriceStars.className = 'plan-card__price plan-card__price--old';
        oldPriceStars.textContent = plan.price_stars + ' ⭐';
        starsBlock.appendChild(oldPriceStars);
      } else {
        var priceStars = document.createElement('span');
        priceStars.className = 'plan-card__price plan-card__price--stars';
        priceStars.textContent = plan.price_stars + ' ⭐';
        starsBlock.appendChild(priceStars);
      }
      priceWrap.appendChild(starsBlock);

      var action = document.createElement('div');
      action.className = 'plan-card__action';
      action.textContent = 'Выбрать тариф';
      priceWrap.appendChild(action);

      inner.appendChild(info);
      inner.appendChild(priceWrap);
      wrapper.appendChild(inner);

      wrapper.addEventListener('click', function () {
        selectPlan(plan);
        if (tg && tg.HapticFeedback) tg.HapticFeedback.selectionChanged();
      });

      fragment.appendChild(wrapper);
    });

    plansEl.innerHTML = '';
    plansEl.appendChild(fragment);

    document.querySelectorAll('[data-animate]').forEach(function (el) {
      observer.observe(el);
    });
  }


  if (buyBtn) {
    buyBtn.addEventListener('click', function () {
      var pricing = document.getElementById('pricing');
      if (pricing) {
        pricing.scrollIntoView({ behavior: 'smooth' });
      }
      if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
    });
  }

  fetch('/api/plans', { headers: { 'ngrok-skip-browser-warning': 'true' } })
    .then(function (r) {
      if (!r.ok) throw new Error('plans fetch failed: ' + r.status);
      return r.json();
    })
    .then(function (data) {
      if (data.discount) {
        discountEnabled = data.discount.enabled;
        discountPct = data.discount.percentage || 0;
      }
      renderPlans(data.plans || data);
    })
    .catch(function (err) {
      if (plansEl) {
        plansEl.innerHTML = '<p style="color:#c00;text-align:center;padding:20px">Не удалось загрузить тарифы: ' + (err && err.message ? err.message : err) + '</p>';
      }
    });

  fetch('/api/site', { headers: { 'ngrok-skip-browser-warning': 'true' } })
    .then(function (r) { return r.json(); })
    .then(function (cfg) {
      botUsername = cfg.bot_username || '';
      if (cfg.tg_channel_url) {
        var chLink = document.getElementById('channelLink');
        if (chLink) chLink.href = cfg.tg_channel_url;
      }
      if (botUsername) {
        var botLink = document.getElementById('botLink');
        if (botLink) {
          botLink.href = 'https://t.me/' + botUsername;
          botLink.textContent = '@' + botUsername;
        }
      }
      togglePromoAdvantages(!!cfg.promo_enabled);
      if (!checkIsWebApp()) {
        var footer = document.getElementById('browserFooter');
        if (footer) footer.style.display = 'block';
      }
    })
    .catch(function () { togglePromoAdvantages(false); });

  if (window.location.hash === '#pricing') {
    setTimeout(function () {
      var pricing = document.getElementById('pricing');
      if (pricing) pricing.scrollIntoView({ behavior: 'smooth' });
    }, 300);
  }

  var SCREENSHOT_IMAGES = [];

  var carouselDots = document.getElementById('carouselDots');
  var carouselTrack = document.getElementById('carouselTrack');
  var carouselViewport = carouselTrack;
  var totalSlides = 0;
  var carouselIndex = 0;
  var carouselInterval = null;
  var isCarouselPaused = false;
  var carouselScrollFrame = null;
  var carouselPointerStartX = 0;
  var carouselPointerStartY = 0;
  var carouselMoved = false;
  var preloadedImages = {};

  function initCarousel(images) {
    SCREENSHOT_IMAGES = images;
    totalSlides = images.length;
    carouselIndex = 0;

    if (carouselTrack) {
      var fragment = document.createDocumentFragment();
      images.forEach(function (src, i) {
        var item = document.createElement('div');
        item.className = 'carousel__item';
        item.setAttribute('data-index', i);
        var img = document.createElement('img');
        img.src = src;
        img.alt = 'Скриншот ' + (i + 1);
        img.setAttribute('loading', i === 0 ? 'eager' : 'lazy');
        img.setAttribute('decoding', 'async');
        img.setAttribute('draggable', 'false');
        img.setAttribute('sizes', '(min-width: 769px) 1200px, 100vw');
        if (i === 0) img.setAttribute('fetchpriority', 'high');
        item.appendChild(img);
        fragment.appendChild(item);
      });
      carouselTrack.innerHTML = '';
      carouselTrack.appendChild(fragment);
    }

    buildDots();
    updateCarousel();
    startCarouselTimer();

    document.querySelectorAll('.carousel__item').forEach(function (card) {
      card.addEventListener('click', function () {
        if (carouselMoved) {
          carouselMoved = false;
          return;
        }
        var index = parseInt(card.getAttribute('data-index'), 10);
        if (!isNaN(index)) openLightbox(index);
      });
    });
  }

  fetch('/api/images', { headers: { 'ngrok-skip-browser-warning': 'true' } })
    .then(function (r) {
      if (!r.ok) throw new Error('images fetch failed: ' + r.status);
      return r.json();
    })
    .then(function (data) {
      var images = data.images || [];
      if (images.length === 0) {
        var screenshots = document.getElementById('screenshots');
        if (screenshots) screenshots.style.display = 'none';
        return;
      }
      initCarousel(images);
    })
    .catch(function (err) {
      console.error('Failed to load images:', err);
      var screenshots = document.getElementById('screenshots');
      if (screenshots) screenshots.style.display = 'none';
    });

  function buildDots() {
    if (!carouselDots) return;
    carouselDots.innerHTML = '';
    for (var i = 0; i < totalSlides; i++) {
      var dot = document.createElement('button');
      dot.className = 'carousel__dot';
      dot.setAttribute('aria-label', 'Скриншот ' + (i + 1));
      dot.addEventListener('click', function () {
        var idx = parseInt(this.getAttribute('data-dot-index'), 10);
        setCarousel(idx);
        resetCarouselTimer();
      });
      dot.setAttribute('data-dot-index', i);
      carouselDots.appendChild(dot);
    }
  }

  function updateCarousel() {
    if (totalSlides <= 0) return;
    var dots = document.querySelectorAll('.carousel__dot');
    dots.forEach(function (dot, i) {
      dot.classList.toggle('active', i === carouselIndex);
    });
    preloadAround(carouselIndex);
  }

  function nextCarousel() {
    if (totalSlides <= 0) return;
    carouselIndex = (carouselIndex + 1) % totalSlides;
    scrollCarouselTo(carouselIndex, true);
  }

  function prevCarousel() {
    if (totalSlides <= 0) return;
    carouselIndex = (carouselIndex - 1 + totalSlides) % totalSlides;
    scrollCarouselTo(carouselIndex, true);
  }

  function setCarousel(index, smooth) {
    if (totalSlides <= 0) return;
    carouselIndex = index;
    scrollCarouselTo(carouselIndex, smooth !== false);
  }

  function startCarouselTimer() {
    if (totalSlides <= 1) return;
    stopCarouselTimer();
    carouselInterval = setInterval(function () {
      if (!isCarouselPaused) nextCarousel();
    }, 5000);
  }

  function stopCarouselTimer() {
    if (carouselInterval) {
      clearInterval(carouselInterval);
      carouselInterval = null;
    }
  }

  function resetCarouselTimer() {
    stopCarouselTimer();
    startCarouselTimer();
  }

  function preloadImage(index) {
    if (totalSlides <= 0) return;
    var normalized = (index + totalSlides) % totalSlides;
    var src = SCREENSHOT_IMAGES[normalized];
    if (!src || preloadedImages[src]) return;
    preloadedImages[src] = true;
    var img = new Image();
    img.decoding = 'async';
    img.src = src;
    if (img.decode) img.decode().catch(function () {});
  }

  function preloadAround(index) {
    preloadImage(index);
    preloadImage(index + 1);
    preloadImage(index - 1);
  }

  function scrollCarouselTo(index, smooth) {
    if (!carouselViewport) {
      updateCarousel();
      return;
    }
    var left = index * carouselViewport.clientWidth;
    try {
      carouselViewport.scrollTo({
        left: left,
        behavior: smooth ? 'smooth' : 'auto'
      });
    } catch (e) {
      carouselViewport.scrollLeft = left;
    }
    updateCarousel();
  }

  function syncCarouselFromScroll() {
    if (!carouselViewport || totalSlides <= 0) return;
    if (carouselScrollFrame) return;
    carouselScrollFrame = requestAnimationFrame(function () {
      carouselScrollFrame = null;
      var width = carouselViewport.clientWidth || 1;
      var index = Math.max(0, Math.min(totalSlides - 1, Math.round(carouselViewport.scrollLeft / width)));
      if (index !== carouselIndex) {
        carouselIndex = index;
        updateCarousel();
      }
    });
  }

  function markCarouselPointerStart(e) {
    carouselPointerStartX = e.clientX || 0;
    carouselPointerStartY = e.clientY || 0;
    carouselMoved = false;
    isCarouselPaused = true;
  }

  function markCarouselPointerMove(e) {
    var dx = Math.abs((e.clientX || 0) - carouselPointerStartX);
    var dy = Math.abs((e.clientY || 0) - carouselPointerStartY);
    if (dx > 10 || dy > 10) carouselMoved = true;
  }

  function markCarouselPointerEnd() {
    isCarouselPaused = false;
    resetCarouselTimer();
    setTimeout(function () { carouselMoved = false; }, 160);
  }

  function forwardVerticalCarouselWheel(e) {
    if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
    e.preventDefault();
    window.scrollBy({ top: e.deltaY, left: 0, behavior: 'auto' });
  }

  var carouselEl = document.getElementById('carousel');
  if (carouselEl) {
    carouselEl.addEventListener('mouseenter', function () { isCarouselPaused = true; });
    carouselEl.addEventListener('mouseleave', function () { isCarouselPaused = false; });
  }
  if (carouselViewport) {
    carouselViewport.addEventListener('scroll', syncCarouselFromScroll, { passive: true });
    carouselViewport.addEventListener('pointerdown', markCarouselPointerStart, { passive: true });
    carouselViewport.addEventListener('pointermove', markCarouselPointerMove, { passive: true });
    carouselViewport.addEventListener('pointerup', markCarouselPointerEnd, { passive: true });
    carouselViewport.addEventListener('pointercancel', markCarouselPointerEnd, { passive: true });
    carouselViewport.addEventListener('wheel', forwardVerticalCarouselWheel, { passive: false });
  }

  var carouselPrevBtn = document.getElementById('carouselPrev');
  var carouselNextBtn = document.getElementById('carouselNext');
  if (carouselPrevBtn) {
    carouselPrevBtn.addEventListener('click', function () {
      prevCarousel();
      resetCarouselTimer();
    });
  }
  if (carouselNextBtn) {
    carouselNextBtn.addEventListener('click', function () {
      nextCarousel();
      resetCarouselTimer();
    });
  }

  var lightbox = document.getElementById('lightbox');
  var lightboxImage = document.getElementById('lightboxImage');
  var lightboxCounter = document.getElementById('lightboxCounter');
  var lightboxClose = document.getElementById('lightboxClose');
  var lightboxPrev = document.getElementById('lightboxPrev');
  var lightboxNext = document.getElementById('lightboxNext');
  var lightboxBackdrop = document.getElementById('lightboxBackdrop');
  var zoomInBtn = document.getElementById('zoomInBtn');
  var zoomOutBtn = document.getElementById('zoomOutBtn');
  var lightboxZoomInfo = document.getElementById('lightboxZoomInfo');
  
  var currentImageIndex = 0;
  var previousImageIndex = 0;
  var isLightboxOpen = false;
  var isAnimating = false;
  
  var currentZoom = 1;
  var maxZoom = 3;
  var minZoom = 1;
  var zoomStep = 0.3;
  var currentX = 0;
  var currentY = 0;
  var isDragging = false;
  var dragStartX = 0;
  var dragStartY = 0;
  var dragStartTouchX = 0;
  var dragStartTouchY = 0;
  var lastTouchDistance = 0;
  var lightboxBaseWidth = 0;
  var lightboxBaseHeight = 0;
  var lightboxTransformFrame = null;
  var zoomUiFrame = null;

  function syncLightboxMetrics() {
    if (!lightboxImage) return;
    lightboxBaseWidth = lightboxImage.clientWidth || lightboxImage.naturalWidth || window.innerWidth;
    lightboxBaseHeight = lightboxImage.clientHeight || lightboxImage.naturalHeight || window.innerHeight;
  }

  function scheduleLightboxImageTransform() {
    if (lightboxTransformFrame) return;
    lightboxTransformFrame = requestAnimationFrame(function () {
      lightboxTransformFrame = null;
      updateLightboxImageTransform();
    });
  }

  function scheduleZoomUiUpdate() {
    if (zoomUiFrame) return;
    zoomUiFrame = requestAnimationFrame(function () {
      zoomUiFrame = null;
      updateZoomDisplay();
      updateZoomButtons();
    });
  }

  function openLightbox(index) {
    currentImageIndex = index;
    previousImageIndex = index;
    isLightboxOpen = true;
    currentZoom = 1;
    currentX = 0;
    currentY = 0;
    lightboxImage.src = SCREENSHOT_IMAGES[currentImageIndex];
    lightboxImage.alt = 'Скриншот ' + (currentImageIndex + 1);
    lightboxCounter.textContent = (currentImageIndex + 1) + ' / ' + totalSlides;
    lightboxImage.className = 'lightbox__image zoom-in';
    lightboxImage.style.transform = '';
    requestAnimationFrame(syncLightboxMetrics);
    updateZoomDisplay();
    updateZoomButtons();
    lightbox.classList.add('active');
    document.body.style.overflow = 'hidden';
    setTimeout(function () {
      if (isLightboxOpen && lightboxImage) {
        lightboxImage.className = 'lightbox__image';
      }
    }, 450);
  }

  function updateZoomDisplay() {
    var zoomPercent = Math.round(currentZoom * 100);
    if (lightboxZoomInfo) lightboxZoomInfo.textContent = zoomPercent + '%';
  }

  function updateZoomButtons() {
    if (zoomInBtn) zoomInBtn.disabled = currentZoom >= maxZoom;
    if (zoomOutBtn) zoomOutBtn.disabled = currentZoom <= minZoom;
  }

  function resetZoom() {
    currentZoom = 1;
    currentX = 0;
    currentY = 0;
    if (lightboxImage) {
      lightboxImage.style.transform = '';
      lightboxImage.classList.remove('animated-transform');
    }
    updateZoomDisplay();
    updateZoomButtons();
  }

  function updateLightboxImageTransform() {
    lightboxImage.classList.remove('zoom-in', 'slide-in-right', 'slide-in-left', 'slide-out-right', 'slide-out-left');
    if (!lightboxBaseWidth || !lightboxBaseHeight) syncLightboxMetrics();
    
    var viewW = window.innerWidth;
    var viewH = window.innerHeight;
    var imgW = lightboxBaseWidth || lightboxImage.clientWidth || viewW;
    var imgH = lightboxBaseHeight || lightboxImage.clientHeight || viewH;
    
    var visualW = imgW * currentZoom;
    var visualH = imgH * currentZoom;
    
    var maxX = Math.max(0, (visualW - viewW) / 2);
    var maxY = Math.max(0, (visualH - viewH) / 2);
    
    currentX = Math.max(-maxX, Math.min(maxX, currentX));
    currentY = Math.max(-maxY, Math.min(maxY, currentY));
    
    lightboxImage.style.transform = 'translate3d(' + currentX + 'px, ' + currentY + 'px, 0) scale(' + currentZoom + ')';
  }

  function zoomIn() {
    if (currentZoom >= maxZoom) return;
    syncLightboxMetrics();
    currentZoom = Math.min(currentZoom + zoomStep, maxZoom);
    lightboxImage.classList.add('animated-transform');
    updateLightboxImageTransform();
    updateZoomDisplay();
    updateZoomButtons();
    setTimeout(function () {
      lightboxImage.classList.remove('animated-transform');
    }, 250);
  }

  function zoomOut() {
    if (currentZoom <= minZoom) return;
    syncLightboxMetrics();
    currentZoom = Math.max(currentZoom - zoomStep, minZoom);
    if (currentZoom === minZoom) {
      currentX = 0;
      currentY = 0;
    }
    lightboxImage.classList.add('animated-transform');
    updateLightboxImageTransform();
    updateZoomDisplay();
    updateZoomButtons();
    setTimeout(function () {
      lightboxImage.classList.remove('animated-transform');
    }, 250);
  }

  function closeLightbox() {
    if (isAnimating) return;
    isLightboxOpen = false;
    resetZoom();
    lightbox.classList.remove('active');
    document.body.style.overflow = '';
    setTimeout(function () {
      lightboxImage.className = 'lightbox__image';
      lightboxImage.style.transform = '';
    }, 350);
  }

  function navigateLightbox(direction) {
    if (isAnimating) return;
    isAnimating = true;
    resetZoom();
    previousImageIndex = currentImageIndex;
    currentImageIndex = (currentImageIndex + direction + totalSlides) % totalSlides;

    var goingRight = direction > 0;
    if (Math.abs(currentImageIndex - previousImageIndex) > totalSlides / 2) {
      goingRight = !goingRight;
    }

    var slideOutClass = goingRight ? 'slide-out-right' : 'slide-out-left';
    var slideInClass = goingRight ? 'slide-in-left' : 'slide-in-right';

    lightboxImage.className = 'lightbox__image ' + slideOutClass;

    setTimeout(function () {
      lightboxImage.src = SCREENSHOT_IMAGES[currentImageIndex];
      lightboxImage.alt = 'Скриншот ' + (currentImageIndex + 1);
      lightboxCounter.textContent = (currentImageIndex + 1) + ' / ' + totalSlides;
      lightboxImage.className = 'lightbox__image ' + slideInClass;
      requestAnimationFrame(syncLightboxMetrics);
      updateZoomDisplay();
      updateZoomButtons();

      setTimeout(function () {
        lightboxImage.className = 'lightbox__image';
        isAnimating = false;
      }, 350);
    }, 200);
  }

  if (carouselTrack) {
    carouselTrack.addEventListener('dragstart', function (e) {
      e.preventDefault();
    });
  }

  if (zoomInBtn) {
    zoomInBtn.addEventListener('click', function () {
      zoomIn();
      if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
    });
  }
  if (zoomOutBtn) {
    zoomOutBtn.addEventListener('click', function () {
      zoomOut();
      if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
    });
  }

  if (lightboxImage) {
    lightboxImage.addEventListener('load', function () {
      syncLightboxMetrics();
      if (isLightboxOpen && currentZoom > 1) updateLightboxImageTransform();
    });

    lightboxImage.addEventListener('mousedown', function (e) {
      if (currentZoom <= 1) return;
      isDragging = true;
      dragStartX = e.clientX - currentX;
      dragStartY = e.clientY - currentY;
      lightboxImage.classList.add('grabbing');
      e.preventDefault();
    });

    lightboxImage.addEventListener('touchstart', function (e) {
      if (!isLightboxOpen) return;
      if (e.touches.length === 2) {
        e.preventDefault();
        lastTouchDistance = Math.hypot(
          e.touches[0].clientX - e.touches[1].clientX,
          e.touches[0].clientY - e.touches[1].clientY
        );
        isDragging = false;
      } else if (currentZoom > 1 && e.touches.length === 1) {
        isDragging = true;
        dragStartTouchX = e.touches[0].clientX - currentX;
        dragStartTouchY = e.touches[0].clientY - currentY;
      }
    }, { passive: false });

    document.addEventListener('mousemove', function (e) {
      if (!isDragging || !isLightboxOpen || currentZoom <= 1) return;
      currentX = e.clientX - dragStartX;
      currentY = e.clientY - dragStartY;
      scheduleLightboxImageTransform();
    });

    document.addEventListener('touchmove', function (e) {
      if (!isLightboxOpen) return;
      if (e.touches.length === 2 && lastTouchDistance) {
        e.preventDefault();
        var currentDistance = Math.hypot(
          e.touches[0].clientX - e.touches[1].clientX,
          e.touches[0].clientY - e.touches[1].clientY
        );
        var scale = currentDistance / lastTouchDistance;
        var newZoom = Math.max(minZoom, Math.min(maxZoom, currentZoom * scale));
        if (newZoom !== currentZoom) {
          currentZoom = newZoom;
          lastTouchDistance = currentDistance;
          scheduleLightboxImageTransform();
          scheduleZoomUiUpdate();
        }
      } else if (isDragging && e.touches.length === 1 && currentZoom > 1) {
        e.preventDefault();
        currentX = e.touches[0].clientX - dragStartTouchX;
        currentY = e.touches[0].clientY - dragStartTouchY;
        scheduleLightboxImageTransform();
      }
    }, { passive: false });

    document.addEventListener('mouseup', function () {
      if (isDragging) {
        isDragging = false;
        lightboxImage.classList.remove('grabbing');
      }
    });

    document.addEventListener('touchend', function () {
      isDragging = false;
      lastTouchDistance = 0;
      updateZoomDisplay();
      updateZoomButtons();
    });

    lightboxImage.addEventListener('wheel', function (e) {
      if (!isLightboxOpen) return;
      e.preventDefault();
      if (e.deltaY < 0) {
        zoomIn();
      } else {
        zoomOut();
      }
    }, { passive: false });
  }

  if (lightboxClose) lightboxClose.addEventListener('click', closeLightbox);
  if (lightboxPrev) lightboxPrev.addEventListener('click', function () { navigateLightbox(-1); });
  if (lightboxNext) lightboxNext.addEventListener('click', function () { navigateLightbox(1); });
  if (lightboxBackdrop) lightboxBackdrop.addEventListener('click', closeLightbox);

  document.addEventListener('keydown', function (e) {
    if (!isLightboxOpen) return;
    if (e.key === 'Escape') closeLightbox();
    if (e.key === 'ArrowLeft') navigateLightbox(-1);
    if (e.key === 'ArrowRight') navigateLightbox(1);
  });
})();
