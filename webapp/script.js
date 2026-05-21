(function () {
  'use strict';

  var tg = window.Telegram && window.Telegram.WebApp;
  var isWebApp = tg && !!tg.initData;

  if (tg) {
    tg.ready();
    if (isWebApp) tg.expand();
  }

  var plansEl = document.getElementById('plansGrid');
  var buyBtn = document.getElementById('heroBuyBtn');
  var scrollBtn = document.getElementById('heroScrollBtn');
  var progressBar = document.getElementById('progressBar');

  function updateProgress() {
    var scrollTop = window.scrollY || document.documentElement.scrollTop;
    var docHeight = document.documentElement.scrollHeight - window.innerHeight;
    var progress = docHeight > 0 ? scrollTop / docHeight : 0;
    if (progressBar) progressBar.style.transform = 'scaleX(' + progress + ')';
  }
  window.addEventListener('scroll', function () { requestAnimationFrame(updateProgress); }, { passive: true });
  window.addEventListener('resize', function () { requestAnimationFrame(updateProgress); }, { passive: true });
  updateProgress();

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

  function togglePromoAdvantages(enabled) {
    document.querySelectorAll('[data-promo-only]').forEach(function (el) {
      el.hidden = !enabled;
      if (enabled) observer.observe(el);
    });
  }

  function botChatUrl() {
    return 'https://t.me/' + (botUsername || 'TestKeyBot_bot');
  }

  function returnToBotChat() {
    if (tg && typeof tg.close === 'function') {
      tg.close();
      return;
    }
    var url = botChatUrl();
    window.location.href = url;
  }

  function sendSelectionFallback(plan) {
    var payload = JSON.stringify({ plan: plan.code, label: plan.label, price_rub: plan.price_rub, price_stars: plan.price_stars });
    if (tg && typeof tg.sendData === 'function') {
      try {
        tg.sendData(payload);
        setTimeout(returnToBotChat, 120);
      } catch (err) {
        returnToBotChat();
      }
    }
  }

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
      if (discountEnabled && discountPct > 0) {
        var inlineDisc = document.createElement('span');
        inlineDisc.className = 'plan-card__discount-inline';
        inlineDisc.textContent = '-' + discountPct + '%';
        name.appendChild(inlineDisc);
      }
      info.appendChild(name);

      if (plan.description) {
        var desc = document.createElement('div');
        desc.className = 'plan-card__desc';
        desc.textContent = plan.description;
        info.appendChild(desc);
      }

      var priceWrap = document.createElement('div');
      priceWrap.className = 'plan-card__price-wrap';

      var rubBlock = document.createElement('div');
      rubBlock.className = 'plan-card__price-block';

      if (discountEnabled && discountPct > 0) {
        var discountedRub = Math.round(plan.price_rub * (100 - discountPct) / 100);
        var currentPriceRub = document.createElement('span');
        currentPriceRub.className = 'plan-card__price plan-card__price--current';
        currentPriceRub.textContent = discountedRub + ' \u20BD';
        rubBlock.appendChild(currentPriceRub);

        var oldPriceRub = document.createElement('span');
        oldPriceRub.className = 'plan-card__price plan-card__price--old';
        oldPriceRub.textContent = plan.price_rub + ' \u20BD';
        rubBlock.appendChild(oldPriceRub);
      } else {
        var priceRub = document.createElement('span');
        priceRub.className = 'plan-card__price';
        priceRub.textContent = plan.price_rub + ' \u20BD';
        rubBlock.appendChild(priceRub);
      }
      priceWrap.appendChild(rubBlock);

      var starsBlock = document.createElement('div');
      starsBlock.className = 'plan-card__price-block';

      if (discountEnabled && discountPct > 0) {
        var discountedStars = Math.round(plan.price_stars * (100 - discountPct) / 100);
        var currentPriceStars = document.createElement('span');
        currentPriceStars.className = 'plan-card__price plan-card__price--stars plan-card__price--current';
        currentPriceStars.textContent = discountedStars + ' \u2b50';
        starsBlock.appendChild(currentPriceStars);

        var oldPriceStars = document.createElement('span');
        oldPriceStars.className = 'plan-card__price plan-card__price--old';
        oldPriceStars.textContent = plan.price_stars + ' \u2b50';
        starsBlock.appendChild(oldPriceStars);
      } else {
        var priceStars = document.createElement('span');
        priceStars.className = 'plan-card__price plan-card__price--stars';
        priceStars.textContent = plan.price_stars + ' \u2b50';
        starsBlock.appendChild(priceStars);
      }
      priceWrap.appendChild(starsBlock);

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
    if (isWebApp && tg && tg.initData) {
      if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
      document.body.style.pointerEvents = 'none';
      fetch('/api/select-plan', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'ngrok-skip-browser-warning': 'true'
        },
        body: JSON.stringify({
          initData: tg.initData,
          plan: plan.code
        })
      })
      .then(function (res) {
        document.body.style.pointerEvents = '';
        if (res.ok) {
          returnToBotChat();
        } else {
          sendSelectionFallback(plan);
        }
      })
      .catch(function () {
        document.body.style.pointerEvents = '';
        sendSelectionFallback(plan);
      });
    } else {
      var startParam = 'buy_' + plan.code;
      var botUrl = 'https://t.me/' + (botUsername || 'TestKeyBot_bot') + '?start=' + startParam;
      window.location.href = botUrl;
    }
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
        plansEl.innerHTML = '<p style="color:#c00;text-align:center;padding:20px">\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0442\u0430\u0440\u0438\u0444\u044b: ' + (err && err.message ? err.message : err) + '</p>';
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
      if (!isWebApp) {
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
    item.style.marginTop = styles.mt + 'px';
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
      return { scale: 1, opacity: 1, w: 320, h: 260, zIndex: 10, mt: -130 };
    } else if (Math.abs(offset) === 1) {
      return { scale: 0.9, opacity: 0.55, w: 180, h: 150, zIndex: 5, mt: -75 };
    } else {
      return { scale: 0.82, opacity: 0.35, w: 160, h: 136, zIndex: 1, mt: -68 };
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

  function prevCarousel() {
    preShiftWrap();
    carouselIndex = (carouselIndex - 1 + totalSlides) % totalSlides;
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

  var carouselEl = document.getElementById('carousel');
  if (carouselEl) {
    carouselEl.addEventListener('mouseenter', function () { isCarouselPaused = true; });
    carouselEl.addEventListener('mouseleave', function () { isCarouselPaused = false; });
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

  var carouselTrack = document.getElementById('carouselTrack');
  if (carouselTrack) {
    carouselTrack.addEventListener('dragstart', function (e) {
      e.preventDefault();
    });
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
