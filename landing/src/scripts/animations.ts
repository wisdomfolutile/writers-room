import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

function initAnimations() {
  // Hero — text entrance
  const heroHeadline = document.querySelector("[data-hero-headline]");
  const heroEyebrow = document.querySelector("[data-hero-eyebrow]");
  const heroSub = document.querySelector("[data-hero-sub]");
  const heroCta = document.querySelector("[data-hero-cta]");
  const heroSearch = document.querySelector("[data-hero-search]");

  if (heroEyebrow) {
    gsap.fromTo(
      heroEyebrow,
      { opacity: 0, y: 10 },
      { opacity: 1, y: 0, duration: 0.6, delay: 0.1, ease: "power2.out" },
    );
  }

  if (heroHeadline) {
    const words = heroHeadline.querySelectorAll(".word");
    gsap.fromTo(
      words,
      { opacity: 0, y: 30 },
      {
        opacity: 1,
        y: 0,
        duration: 0.7,
        stagger: 0.08,
        ease: "power2.out",
      },
    );
  }

  if (heroSub) {
    gsap.fromTo(
      heroSub,
      { opacity: 0, y: 20 },
      { opacity: 1, y: 0, duration: 0.8, delay: 0.5, ease: "power2.out" },
    );
  }

  if (heroCta) {
    gsap.fromTo(
      heroCta,
      { opacity: 0, y: 20 },
      { opacity: 1, y: 0, duration: 0.8, delay: 0.7, ease: "power2.out" },
    );
  }

  if (heroSearch) {
    gsap.fromTo(
      heroSearch,
      { opacity: 0, y: 30, scale: 0.97 },
      {
        opacity: 1,
        y: 0,
        scale: 1,
        duration: 1,
        delay: 0.9,
        ease: "power2.out",
      },
    );
  }

  // Stat bar — counter animation
  document.querySelectorAll("[data-count-to]").forEach((el) => {
    const target = parseInt(el.getAttribute("data-count-to") || "0", 10);
    const suffix = el.getAttribute("data-count-suffix") || "";
    const prefix = el.getAttribute("data-count-prefix") || "";
    const obj = { val: 0 };

    ScrollTrigger.create({
      trigger: el,
      start: "top 85%",
      once: true,
      onEnter: () => {
        gsap.to(obj, {
          val: target,
          duration: 1.5,
          ease: "power1.inOut",
          onUpdate: () => {
            (el as HTMLElement).textContent =
              prefix + Math.round(obj.val).toLocaleString() + suffix;
          },
        });
      },
    });
  });

  // Fade-up elements
  document.querySelectorAll(".fade-up").forEach((el) => {
    gsap.to(el, {
      scrollTrigger: {
        trigger: el,
        start: "top 88%",
        once: true,
      },
      opacity: 1,
      y: 0,
      duration: 0.8,
      ease: "power2.out",
    });
  });

  // Feature cards — staggered entrance
  const featureGrid = document.querySelector("[data-feature-grid]");
  if (featureGrid) {
    const cards = featureGrid.querySelectorAll("[data-feature-card]");
    ScrollTrigger.create({
      trigger: featureGrid,
      start: "top 80%",
      once: true,
      onEnter: () => {
        gsap.fromTo(
          cards,
          { opacity: 0, y: 50 },
          {
            opacity: 1,
            y: 0,
            duration: 0.7,
            stagger: 0.1,
            ease: "power2.out",
          },
        );
      },
    });
  }

  // How it works — pipeline steps
  const pipeline = document.querySelector("[data-pipeline]");
  if (pipeline) {
    const steps = pipeline.querySelectorAll("[data-step]");
    const lines = pipeline.querySelectorAll("[data-line]");

    ScrollTrigger.create({
      trigger: pipeline,
      start: "top 75%",
      once: true,
      onEnter: () => {
        const tl = gsap.timeline();
        steps.forEach((step, i) => {
          tl.fromTo(
            step,
            { opacity: 0, y: 30 },
            { opacity: 1, y: 0, duration: 0.5, ease: "power2.out" },
            i * 0.3,
          );
          if (lines[i]) {
            tl.fromTo(
              lines[i],
              { scaleX: 0 },
              {
                scaleX: 1,
                duration: 0.4,
                ease: "power2.inOut",
                transformOrigin: "left center",
              },
              i * 0.3 + 0.25,
            );
          }
        });
      },
    });
  }

  // Search modes — tab content fade
  document.querySelectorAll("[data-mode-card]").forEach((el) => {
    gsap.fromTo(
      el,
      { opacity: 0, y: 30 },
      {
        scrollTrigger: {
          trigger: el,
          start: "top 85%",
          once: true,
        },
        opacity: 1,
        y: 0,
        duration: 0.7,
        ease: "power2.out",
      },
    );
  });

  // Pricing rows
  const pricingSection = document.querySelector("[data-pricing]");
  if (pricingSection) {
    const rows = pricingSection.querySelectorAll("[data-pricing-row]");
    ScrollTrigger.create({
      trigger: pricingSection,
      start: "top 80%",
      once: true,
      onEnter: () => {
        gsap.fromTo(
          rows,
          { opacity: 0, x: -20 },
          {
            opacity: 1,
            x: 0,
            duration: 0.6,
            stagger: 0.08,
            ease: "power2.out",
          },
        );
      },
    });
  }
}

// Run after DOM is ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initAnimations);
} else {
  initAnimations();
}
