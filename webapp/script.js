(function () {
  'use strict';

  var tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
  }

  var plansEl = document.getElementById('plansGrid');
  var buyBtn = document.getElementById('heroBuyBtn');
  var scrollBtn = document.getElementById('heroScrollBtn');
  var progressBar = document.getElementById('progressBar');

  /* ===== Scroll Progress ===== */
  function updateProgress() {
    var scrollTop = window.scrollY || document.documentElement.scrollTop;
    var docHeight = document.documentElement.scrollHeight - window.innerHeight;
    var progress = docHeight > 0 ? scrollTop / docHeight : 0;
    if (progressBar) progressBar.style.transform = 'scaleX(' + progress + ')';
    requestAnimationFrame(updateProgress);
  }
  window.addEventListener('scroll', function () { requestAnimationFrame(updateProgress); }, { passive: true });
  requestAnimationFrame(updateProgress);

  /* ===== Scroll Animations ===== */
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
      }
    });
  }, { threshold: 0.15, rootMargin: '0px 0px -40px 0px' });

  document.querySelectorAll('[data-animate]').forEach(function (el) {
    observer.observe(el);
  });

  /* ===== Hero Buttons ===== */
  if (scrollBtn) {
    scrollBtn.addEventListener('click', function () {
      var features = document.getElementById('features');
      if (features) features.scrollIntoView({ behavior: 'smooth' });
      if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
    });
  }

  /* ===== Plans ===== */
  function renderPlans(plans) {
    if (!plansEl) return;
    plansEl.innerHTML = '';
    plans.forEach(function (plan) {
      var wrapper = document.createElement('div');
      wrapper.className = 'plan-card';
      wrapper.setAttribute('data-animate', '');
      if (plan.highlighted) wrapper.classList.add('plan-card--highlighted');
      wrapper.dataset.code = plan.code;

      var inner = document.createElement('div');
      inner.className = 'plan-card__inner';

      if (plan.highlighted) {
        var badge = document.createElement('div');
        badge.className = 'plan-card__badge';
        badge.textContent = '\u2b50 Популярный';
        inner.appendChild(badge);
      }

      var info = document.createElement('div');
      info.className = 'plan-card__info';

      var name = document.createElement('div');
      name.className = 'plan-card__name';
      name.textContent = plan.label;
      info.appendChild(name);

      if (plan.description) {
        var desc = document.createElement('div');
        desc.className = 'plan-card__desc';
        desc.textContent = plan.description;
        info.appendChild(desc);
      }

      var priceWrap = document.createElement('div');
      var price = document.createElement('div');
      price.className = 'plan-card__price';
      price.textContent = plan.price_rub + ' \u20BD';
      priceWrap.appendChild(price);

      inner.appendChild(info);
      inner.appendChild(priceWrap);
      wrapper.appendChild(inner);

      wrapper.addEventListener('click', function () {
        selectPlan(plan);
        if (tg && tg.HapticFeedback) tg.HapticFeedback.selectionChanged();
      });

      plansEl.appendChild(wrapper);
    });

    document.querySelectorAll('[data-animate]').forEach(function (el) {
      observer.observe(el);
    });
  }

  function selectPlan(plan) {
    var payload = JSON.stringify({ plan: plan.code, label: plan.label, price_rub: plan.price_rub });
    if (tg && typeof tg.sendData === 'function') {
      tg.sendData(payload);
    } else {
      alert('\u0412\u044b\u0431\u0440\u0430\u043d: ' + plan.label + ' (' + plan.price_rub + ' \u20BD)');
    }
  }

  /* ===== Hero Buy Button ===== */
  if (buyBtn) {
    buyBtn.addEventListener('click', function () {
      var pricing = document.getElementById('pricing');
      if (pricing) {
        pricing.scrollIntoView({ behavior: 'smooth' });
      }
      if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
    });
  }

  /* ===== Fetch Plans ===== */
  fetch('/api/plans', { headers: { 'ngrok-skip-browser-warning': 'true' } })
    .then(function (r) {
      if (!r.ok) throw new Error('plans fetch failed: ' + r.status);
      return r.json();
    })
    .then(renderPlans)
    .catch(function (err) {
      if (plansEl) {
        plansEl.innerHTML = '<p style="color:#c00;text-align:center;padding:20px">\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0442\u0430\u0440\u0438\u0444\u044b: ' + (err && err.message ? err.message : err) + '</p>';
      }
    });

  /* ===== URL hash: scroll to pricing ===== */
  if (window.location.hash === '#pricing') {
    setTimeout(function () {
      var pricing = document.getElementById('pricing');
      if (pricing) pricing.scrollIntoView({ behavior: 'smooth' });
    }, 300);
  }

  /* ===== Carousel ===== */
  var SCREENSHOT_IMAGES = [
    '/static/images/photo_2026-05-17_21-31-23.jpg',
    '/static/images/photo_2026-05-17_21-31-23 (2).jpg',
    '/static/images/photo_2026-05-17_21-31-24.jpg',
    '/static/images/photo_2026-05-17_21-31-24 (2).jpg',
    '/static/images/photo_2026-05-17_21-31-25.jpg',
    '/static/images/photo_2026-05-17_21-31-25 (2).jpg',
    '/static/images/photo_2026-05-17_21-31-26.jpg',
    '/static/images/photo_2026-05-17_21-31-26 (2).jpg'
  ];

  var carouselDots = document.getElementById('carouselDots');
  var carouselItems = document.querySelectorAll('.carousel__item');
  var totalSlides = SCREENSHOT_IMAGES.length;
  var carouselIndex = 0;
  var carouselInterval = null;
  var isCarouselPaused = false;

  function getTranslateX(offset) {
    if (offset === 0) return 0;
    var gap = 15;
    var sign = offset > 0 ? 1 : -1;
    var absOffset = Math.abs(offset);
    var widths = [320, 180, 160, 160, 160, 160, 160, 160];
    var pos = 0;
    for (var i = 0; i < absOffset; i++) {
      pos += widths[i] / 2 + gap + widths[i + 1] / 2;
    }
    return pos * sign;
  }

  function applyItemStyle(item, offset, skipTransition) {
    var styles = getItemStyles(offset);
    var translateX = getTranslateX(offset);
    if (skipTransition) {
      item.style.transition = 'none';
    }
    item.style.transform = 'translateX(' + translateX + 'px) scale(' + styles.scale + ')';
    item.style.opacity = styles.opacity;
    item.style.width = styles.w + 'px';
    item.style.height = styles.h + 'px';
    item.style.zIndex = styles.zIndex;
    item.style.marginLeft = (-(styles.w / 2)) + 'px';
    item.style.marginTop = (-(styles.h / 2)) + 'px';
    if (skipTransition) {
      void item.offsetHeight;
      item.style.transition = '';
    }
  }

  function buildDots() {
    if (!carouselDots) return;
    carouselDots.innerHTML = '';
    for (var i = 0; i < totalSlides; i++) {
      var dot = document.createElement('button');
      dot.className = 'carousel__dot';
      dot.setAttribute('aria-label', '\u0421\u043a\u0440\u0438\u043d\u0448\u043e\u0442 ' + (i + 1));
      dot.addEventListener('click', function () {
        var idx = parseInt(this.getAttribute('data-dot-index'), 10);
        setCarousel(idx);
        resetCarouselTimer();
      });
      dot.setAttribute('data-dot-index', i);
      carouselDots.appendChild(dot);
    }
  }

  function getItemStyles(offset) {
    if (offset === 0) {
      return { scale: 1, opacity: 1, w: 320, h: 225, zIndex: 10 };
    } else if (Math.abs(offset) === 1) {
      return { scale: 0.9, opacity: 0.55, w: 180, h: 130, zIndex: 5 };
    } else {
      return { scale: 0.82, opacity: 0.35, w: 160, h: 118, zIndex: 1 };
    }
  }

  function updateCarousel(skipTransition) {
    var items = document.querySelectorAll('.carousel__item');
    items.forEach(function (item, i) {
      var offset = i - carouselIndex;
      if (offset > totalSlides / 2) offset -= totalSlides;
      if (offset < -totalSlides / 2) offset += totalSlides;
      applyItemStyle(item, offset, skipTransition);
    });

    var dots = document.querySelectorAll('.carousel__dot');
    dots.forEach(function (dot, i) {
      dot.classList.toggle('active', i === carouselIndex);
    });
  }

  function preShiftWrap() {
    var items = document.querySelectorAll('.carousel__item');
    items.forEach(function (item, i) {
      var currentOffset = i - carouselIndex;
      if (currentOffset > totalSlides / 2) currentOffset -= totalSlides;
      if (currentOffset < -totalSlides / 2) currentOffset += totalSlides;

      var nextOffset = i - ((carouselIndex + 1) % totalSlides);
      if (nextOffset > totalSlides / 2) nextOffset -= totalSlides;
      if (nextOffset < -totalSlides / 2) nextOffset += totalSlides;

      var delta = Math.abs(nextOffset - currentOffset);
      if (delta > totalSlides / 2) {
        applyItemStyle(item, nextOffset, true);
      }
    });
  }

  function nextCarousel() {
    preShiftWrap();
    carouselIndex = (carouselIndex + 1) % totalSlides;
    updateCarousel();
  }

  function setCarousel(index) {
    var items = document.querySelectorAll('.carousel__item');
    items.forEach(function (item, i) {
      var currentOffset = i - carouselIndex;
      if (currentOffset > totalSlides / 2) currentOffset -= totalSlides;
      if (currentOffset < -totalSlides / 2) currentOffset += totalSlides;

      var nextOffset = i - index;
      if (nextOffset > totalSlides / 2) nextOffset -= totalSlides;
      if (nextOffset < -totalSlides / 2) nextOffset += totalSlides;

      var delta = Math.abs(nextOffset - currentOffset);
      if (delta > totalSlides / 2) {
        applyItemStyle(item, nextOffset, true);
      }
    });
    carouselIndex = index;
    updateCarousel();
  }

  function startCarouselTimer() {
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

  buildDots();
  updateCarousel();
  startCarouselTimer();

  carouselItems.forEach(function (item) {
    item.addEventListener('click', function () {
      var idx = parseInt(this.getAttribute('data-index'), 10);
      if (!isNaN(idx)) {
        setCarousel(idx);
        resetCarouselTimer();
      }
    });
  });

  var carouselEl = document.getElementById('carousel');
  if (carouselEl) {
    carouselEl.addEventListener('mouseenter', function () { isCarouselPaused = true; });
    carouselEl.addEventListener('mouseleave', function () { isCarouselPaused = false; });
  }

  /* ===== Carousel Swipe/Drag ===== */
  (function () {
    var track = document.getElementById('carouselTrack');
    if (!track) return;

    var startX = 0, currentX = 0, isDragging = false;

    function onStart(e) {
      isDragging = true;
      startX = e.type === 'touchstart' ? e.touches[0].clientX : e.clientX;
      track.style.transition = 'none';
    }

    function onMove(e) {
      if (!isDragging) return;
      e.preventDefault();
      currentX = (e.type === 'touchmove' ? e.touches[0].clientX : e.clientX) - startX;
      var items = document.querySelectorAll('.carousel__item');
      items.forEach(function (item) {
        var currentTransform = item.style.transform || '';
        var baseMatch = currentTransform.match(/translateX\(([^)]+)px\)/);
        var baseX = baseMatch ? parseFloat(baseMatch[1]) : 0;
        item.style.transform = currentTransform.replace(/translateX\([^)]+px\)/, 'translateX(' + (baseX + currentX * 0.3) + 'px)');
      });
    }

    function onEnd() {
      if (!isDragging) return;
      isDragging = false;
      track.style.transition = '';
      if (Math.abs(currentX) > 50) {
        if (currentX < 0) { nextCarousel(); resetCarouselTimer(); }
        else { carouselIndex = (carouselIndex - 1 + totalSlides) % totalSlides; updateCarousel(); resetCarouselTimer(); }
      } else {
        updateCarousel();
      }
      currentX = 0;
    }

    track.addEventListener('touchstart', onStart, { passive: true });
    track.addEventListener('touchmove', onMove, { passive: false });
    track.addEventListener('touchend', onEnd);
    track.addEventListener('mousedown', onStart);
    track.addEventListener('mousemove', onMove);
    track.addEventListener('mouseup', onEnd);
    track.addEventListener('mouseleave', function () { if (isDragging) onEnd(); });
  })();

  /* ===== Lightbox ===== */
  var lightbox = document.getElementById('lightbox');
  var lightboxImage = document.getElementById('lightboxImage');
  var lightboxCounter = document.getElementById('lightboxCounter');
  var lightboxClose = document.getElementById('lightboxClose');
  var lightboxPrev = document.getElementById('lightboxPrev');
  var lightboxNext = document.getElementById('lightboxNext');
  var lightboxBackdrop = document.getElementById('lightboxBackdrop');
  var currentImageIndex = 0;
  var previousImageIndex = 0;
  var isLightboxOpen = false;
  var isAnimating = false;

  function openLightbox(index) {
    currentImageIndex = index;
    previousImageIndex = index;
    isLightboxOpen = true;
    lightboxImage.src = SCREENSHOT_IMAGES[currentImageIndex];
    lightboxImage.alt = '\u0421\u043a\u0440\u0438\u043d\u0448\u043e\u0442 ' + (currentImageIndex + 1);
    lightboxCounter.textContent = (currentImageIndex + 1) + ' / ' + totalSlides;
    lightboxImage.className = 'lightbox__image zoom-in';
    lightbox.classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  function closeLightbox() {
    if (isAnimating) return;
    isLightboxOpen = false;
    lightbox.classList.remove('active');
    document.body.style.overflow = '';
    setTimeout(function () {
      lightboxImage.className = 'lightbox__image';
    }, 350);
  }

  function navigateLightbox(direction) {
    if (isAnimating) return;
    isAnimating = true;
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
      lightboxImage.alt = '\u0421\u043a\u0440\u0438\u043d\u0448\u043e\u0442 ' + (currentImageIndex + 1);
      lightboxCounter.textContent = (currentImageIndex + 1) + ' / ' + totalSlides;
      lightboxImage.className = 'lightbox__image ' + slideInClass;

      setTimeout(function () {
        isAnimating = false;
      }, 350);
    }, 200);
  }

  document.querySelectorAll('.carousel__item').forEach(function (card) {
    card.addEventListener('click', function () {
      var index = parseInt(card.getAttribute('data-index'), 10);
      if (!isNaN(index)) openLightbox(index);
    });
  });

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
