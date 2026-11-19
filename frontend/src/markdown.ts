import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'

const md = new MarkdownIt({ linkify: true, breaks: true })

// 回答里的链接（引用来源）一律在新标签页打开
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

/** 把模型输出的 Markdown 转成可安全插入页面的 HTML。 */
export function renderMarkdown(text: string): string {
  return DOMPurify.sanitize(md.render(text), { ADD_ATTR: ['target'] })
}

/**
 * 把正在生成的 Markdown 按空行切成若干段（代码块内部不切）。
 * 生成过程中只有最后一段在变，前面各段的 HTML 不变，页面就不必整体重绘；
 * 整体重绘会让往上翻看的用户看到闪烁、滚动位置跳动。
 */
export function splitBlocks(text: string): string[] {
  const blocks: string[] = []
  let current: string[] = []
  let fenced = false
  for (const line of text.split('\n')) {
    if (/^\s*(```|~~~)/.test(line)) fenced = !fenced
    if (!fenced && line.trim() === '' && current.length) {
      blocks.push(current.join('\n'))
      current = []
      continue
    }
    if (line.trim() !== '' || current.length) current.push(line)
  }
  if (current.length) blocks.push(current.join('\n'))
  return blocks
}

const cache = new Map<string, string>()

/** 带缓存的渲染：同一段文字只渲染一次。生成中的回答每次只需重新渲染最后一段。 */
export function renderCached(text: string): string {
  let html = cache.get(text)
  if (html === undefined) {
    html = renderMarkdown(text)
    if (cache.size > 2000) cache.clear()
    cache.set(text, html)
  }
  return html
}
