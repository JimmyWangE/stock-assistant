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
