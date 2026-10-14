import { expect, it } from 'vitest';
import postcss from 'postcss';
import tailwindcss from 'tailwindcss';
import config from './tailwind.config.js';

it('activates compiled dark utilities beneath the root dark class', async () => {
  const result = await postcss([tailwindcss({
    ...config,
    content: [{ raw: '<div class="bg-white dark:bg-zinc-900 text-slate-800 dark:text-zinc-100"></div>', extension: 'html' }],
  })]).process('@tailwind utilities;', { from: undefined });

  const element = document.createElement('div');
  element.className = 'bg-white dark:bg-zinc-900 text-slate-800 dark:text-zinc-100';
  document.body.append(element);
  const selectors = [];
  result.root.walkRules(rule => {
    if (rule.selector.includes('dark\\:')) selectors.push(rule.selector);
  });
  expect(selectors).toHaveLength(2);
  const wasDark = document.documentElement.classList.contains('dark');
  try {
    document.documentElement.classList.remove('dark');
    for (const selector of selectors) expect(element.matches(selector)).toBe(false);
    document.documentElement.classList.add('dark');
    for (const selector of selectors) expect(element.matches(selector)).toBe(true);
  } finally {
    document.documentElement.classList.toggle('dark', wasDark);
    element.remove();
  }
});
