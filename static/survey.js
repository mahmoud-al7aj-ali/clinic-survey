(function () {
  const TOTAL = window.SURVEY_TOTAL || 0;
  const answers = {};

  const progressDock = document.getElementById('progress-dock');
  const progressFill = document.getElementById('progress-fill');
  const progressText = document.getElementById('progress-text');
  const btnGotoSubmit = document.getElementById('btn-goto-submit');
  const submitMsg = document.getElementById('submit-msg');
  const successBanner = document.getElementById('success-banner');

  function countAnswered() {
    return Object.keys(answers).length;
  }

  function updateProgress() {
    const n = countAnswered();
    const pct = TOTAL ? Math.round((n / TOTAL) * 100) : 0;
    progressFill.style.width = pct + '%';
    progressText.textContent = n + ' / ' + TOTAL;
    if (btnGotoSubmit) btnGotoSubmit.disabled = n < TOTAL;
    document.querySelectorAll('.ft tbody tr[data-feature-num]').forEach(function (row) {
      const id = row.dataset.featureNum;
      row.classList.toggle('row-answered', !!answers[id]);
      row.classList.remove('row-missing');
    });
  }

  function showDock() {
    if (!progressDock) return;
    progressDock.classList.remove('is-hidden');
    progressDock.classList.add('is-visible');
    document.body.classList.add('has-dock');
  }

  function setMsg(text, type) {
    submitMsg.textContent = text;
    submitMsg.className = 'submit-msg' + (type ? ' ' + type : '');
  }

  document.querySelectorAll('.ft tbody tr[data-feature-num]').forEach(function (row) {
    const num = row.dataset.featureNum;
    row.querySelectorAll('.rb[data-value]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        row.querySelectorAll('.rb').forEach(function (b) {
          const on = b === btn;
          b.classList.toggle('selected', on);
          b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        answers[num] = btn.dataset.value;
        showDock();
        updateProgress();
      });
    });
  });

  document.getElementById('btn-start')?.addEventListener('click', function () {
    document.querySelector('.page')?.scrollIntoView({ behavior: 'smooth' });
    showDock();
  });

  if ('IntersectionObserver' in window) {
    const pageObserver = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-inview');
            pageObserver.unobserve(entry.target);
          }
        });
      },
      { rootMargin: '0px 0px -8% 0px', threshold: 0.08 }
    );
    document.querySelectorAll('.page').forEach(function (page) {
      pageObserver.observe(page);
    });
  } else {
    document.querySelectorAll('.page').forEach(function (page) {
      page.classList.add('is-inview');
    });
  }

  const detailModal = document.getElementById('detail-modal');
  const detailTitle = document.getElementById('detail-modal-title');
  const detailBody = document.getElementById('detail-modal-body');
  const detailClose = document.getElementById('detail-modal-close');
  const detailBackdrop = document.getElementById('detail-modal-backdrop');

  function openDetail(featureId, titleText) {
    const tpl = document.getElementById('long-desc-' + featureId);
    if (!tpl || !detailModal) return;
    detailTitle.textContent = titleText || '';
    detailBody.textContent = tpl.content.textContent.trim();
    detailModal.classList.remove('is-hidden');
    requestAnimationFrame(function () {
      detailModal.classList.add('is-open');
    });
    document.body.style.overflow = 'hidden';
    detailClose.focus();
  }

  function closeDetail() {
    if (!detailModal) return;
    detailModal.classList.remove('is-open');
    document.body.style.overflow = '';
    window.setTimeout(function () {
      if (!detailModal.classList.contains('is-open')) {
        detailModal.classList.add('is-hidden');
      }
    }, 280);
  }

  document.querySelectorAll('.btn-details').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      const row = btn.closest('tr');
      const titleEl = row?.querySelector('.fn');
      openDetail(btn.dataset.featureId, titleEl?.textContent || '');
    });
  });

  detailClose?.addEventListener('click', closeDetail);
  detailBackdrop?.addEventListener('click', closeDetail);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && detailModal && detailModal.classList.contains('is-open')) {
      closeDetail();
    }
  });

  function scrollToSubmit() {
    const n = countAnswered();
    if (n < TOTAL) {
      const missing = document.querySelector('.ft tbody tr:not(.row-answered)');
      missing?.classList.add('row-missing');
      missing?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      setMsg('يرجى تقييم جميع الميزات (' + n + ' من ' + TOTAL + ')', 'err');
      return false;
    }
    document.getElementById('submit-panel')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    return true;
  }

  btnGotoSubmit?.addEventListener('click', scrollToSubmit);

  document.getElementById('btn-save')?.addEventListener('click', async function () {
    if (!scrollToSubmit()) return;

    const doctorEl = document.getElementById('doctor-name');
    const clinicEl = document.getElementById('clinic-name');
    const phoneEl = document.getElementById('phone');
    const doctor = doctorEl.value.trim();
    const clinic = clinicEl.value.trim();
    const phone = phoneEl.value.trim();

    [doctorEl, clinicEl, phoneEl].forEach(function (el) {
      el.classList.remove('field-invalid');
    });

    if (!doctor || !clinic || !phone) {
      if (!doctor) doctorEl.classList.add('field-invalid');
      if (!clinic) clinicEl.classList.add('field-invalid');
      if (!phone) phoneEl.classList.add('field-invalid');
      setMsg('يرجى إدخال اسم الطبيب واسم العيادة ورقم الهاتف', 'err');
      document.querySelector('.field-invalid')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      document.querySelector('.field-invalid')?.focus();
      return;
    }

    const btn = document.getElementById('btn-save');
    btn.disabled = true;
    setMsg('جاري الحفظ...', '');

    try {
      const res = await fetch('/api/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          doctor_name: doctor,
          clinic_name: clinic,
          phone: phone,
          email: document.getElementById('email').value.trim(),
          notes: document.getElementById('notes').value.trim(),
          answers: answers,
        }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        setMsg(data.error || 'حدث خطأ', 'err');
        btn.disabled = false;
        return;
      }
      setMsg(data.message || 'تم الحفظ', 'ok');
      if (successBanner) {
        successBanner.textContent = data.message;
        successBanner.classList.add('show');
      }
      btn.textContent = data.updated ? 'تم التحديث ✓' : 'تم الإرسال ✓';
    } catch (e) {
      setMsg('تعذر الاتصال بالخادم', 'err');
      btn.disabled = false;
    }
  });

  ['doctor-name', 'clinic-name', 'phone'].forEach(function (id) {
    document.getElementById(id)?.addEventListener('input', function () {
      if (this.value.trim()) this.classList.remove('field-invalid');
    });
  });

  updateProgress();
})();
