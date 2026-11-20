<script setup lang="ts">
import { MagicStick, Refresh } from '@element-plus/icons-vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { hawkeyeApi, type HawkeyeDay, type HawkeyePick, type HawkeyeResult } from '../api'
import { signed, trend } from '../market'

const router = useRouter()
const result = ref<HawkeyeResult | null>(null)
const history = ref<HawkeyeDay[]>([])
const loading = ref(false)
const error = ref('')
const showRules = ref(false)
let timer: ReturnType<typeof setInterval> | undefined

async function load(): Promise<void> {
  if (document.hidden) return
  loading.value = true
  try {
    const [today, past] = await Promise.all([hawkeyeApi.today(), hawkeyeApi.history()])
    result.value = today
    history.value = past
    error.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

const phaseText = computed(() => {
  const r = result.value
  if (!r) return ''
  if (r.preview) return `${r.phase} · 下一交易日预览：按利好强度排序，开盘后再加入盘面确认`
  if (r.phase === '盘中') return '盘中：利好强度 + 开盘表现综合评分'
  return `${r.phase}：按利好强度排序，开盘后加入盘面确认`
})

function askAi(p: HawkeyePick): void {
  const titles = p.catalysts.map((c) => `《${c.title}》`).join('、')
  router.push({
    name: 'new-chat',
    query: { q: `${p.name}（${p.code}）发布了${titles}，结合公司基本面、近期走势和今天的盘面，分析这个利好的分量和持续性，以及需要注意的风险` },
  })
}

onMounted(() => {
  load()
  // 结果后端 60 秒更新一次，页面同步刷新
  timer = setInterval(load, 60_000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <div class="hawkeye">
    <div class="page">
      <header class="page-head">
        <div>
          <h1>火眼金睛</h1>
          <p class="sub">
            从上一交易日收盘以来的公告中找出重大利好，再用开盘表现确认，给出当日值得重点研究的股票。
          </p>
        </div>
        <div class="actions">
          <el-button text @click="showRules = !showRules">{{ showRules ? '收起评分规则' : '评分规则' }}</el-button>
          <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        </div>
      </header>

      <section v-if="showRules" class="card rules">
        <h2>评分规则</h2>
        <div class="rule-grid">
          <div>
            <h3>利好强度（公告）</h3>
            <ul>
              <li>业绩预增（净利润增幅 ≥ 50%）或扭亏：25 分起，增幅越大越高，最多 40</li>
              <li>重大合同 / 中标：20；重组 / 收购控制权：20</li>
              <li>新药或医疗器械获批上市：18；控股股东增持计划：15</li>
              <li>回购方案：12；临床试验获批：8；股权激励草案：8</li>
              <li>只计首次披露；律师意见、进展、修订稿等后续文件不重复计分</li>
            </ul>
          </div>
          <div>
            <h3>盘面确认（开盘后）</h3>
            <ul>
              <li>高开 1%~7%：+15；高开超过 7%：+8（追高风险）；低开：−10</li>
              <li>量比 ≥ 5：+15；量比 ≥ 2：+10</li>
              <li>开盘后继续走高：+5；较开盘回落超过 2%：−8</li>
            </ul>
          </div>
          <div>
            <h3>风险扣分</h3>
            <ul>
              <li>同期有减持、立案、处罚、预亏等公告：−25</li>
              <li>开盘一字涨停未打开（买不进）：−10</li>
              <li>总市值小于 30 亿：−5；ST 股票不入选</li>
            </ul>
          </div>
        </div>
        <p class="rule-note">
          规则由程序执行、可逐条核对，不使用模型判断。每个交易日 9:35 后的名单会定格保存，下方"历史表现"统计入选后的实际涨跌，用来检验规则是否有效。
        </p>
      </section>

      <p v-if="error" class="error">{{ error }}</p>
      <p v-else-if="!result" class="muted">正在扫描公告…（首次约需 10 秒）</p>

      <template v-if="result">
        <div class="status-bar">
          <span class="phase" :class="{ live: result.phase === '盘中' }">{{ result.phase }}</span>
          <span>{{ phaseText }}</span>
          <span class="muted">
            {{ result.window }} · 扫描公告 {{ result.scanned }} 条 · 更新于 {{ result.as_of.slice(11) }}
          </span>
        </div>

        <p v-if="!result.picks.length" class="muted">这段时间没有符合条件的重大利好公告。</p>

        <div class="picks">
          <article v-for="(p, i) in result.picks" :key="p.code" class="pick card">
            <div class="rank" :class="{ top: i < 3 }">{{ i + 1 }}</div>
            <div class="main">
              <div class="title-row">
                <router-link :to="`/stock/${p.code}`" class="name">{{ p.name }}</router-link>
                <span class="code">{{ p.code }}</span>
                <span class="stars" :aria-label="`${p.stars} 星`">
                  <i v-for="n in 5" :key="n" :class="{ on: n <= p.stars }">★</i>
                </span>
                <span class="score">
                  {{ p.score }} 分<small>（利好 {{ p.catalyst_score }}{{ p.market_score >= 0 ? ' + ' : ' − ' }}盘面与风险 {{ Math.abs(p.market_score) }}）</small>
                </span>
              </div>

              <ul class="catalysts">
                <li v-for="c in p.catalysts" :key="c.url + c.title">
                  <span class="kind">{{ c.kind }}</span>
                  <a :href="c.url" target="_blank" rel="noopener noreferrer">{{ c.title }}</a>
                  <span class="date">{{ c.date.slice(5) }}</span>
                </li>
              </ul>

              <div class="chips">
                <span v-for="r in p.reasons" :key="r" class="chip good">{{ r }}</span>
                <span v-for="r in p.risks" :key="r" class="chip risk">{{ r }}</span>
              </div>
              <ul v-if="p.warnings.length" class="warnings">
                <li v-for="w in p.warnings" :key="w.url">
                  风险公告：<a :href="w.url" target="_blank" rel="noopener noreferrer">{{ w.title }}</a>
                </li>
              </ul>
            </div>

            <div class="quote">
              <div class="price" :class="trend(p.pct ?? 0)">{{ p.price ? p.price.toFixed(2) : '—' }}</div>
              <div class="pct" :class="trend(p.pct ?? 0)">{{ p.pct == null ? '—' : signed(p.pct) + '%' }}</div>
              <dl>
                <div><dt>开盘</dt><dd>{{ p.gap == null ? '未开盘' : signed(p.gap) + '%' }}</dd></div>
                <div><dt>量比</dt><dd>{{ p.volume_ratio == null ? '—' : p.volume_ratio.toFixed(2) }}</dd></div>
                <div><dt>市值</dt><dd>{{ p.mktcap.toFixed(0) }} 亿</dd></div>
              </dl>
              <el-button size="small" type="primary" plain :icon="MagicStick" @click="askAi(p)">AI 深度解读</el-button>
            </div>
          </article>
        </div>
      </template>

      <section class="card history">
        <h2>历史表现<span>每天 9:35 定格的三星及以上名单，从入选当天开盘价算到现在</span></h2>
        <p v-if="!history.length" class="muted">还没有定格记录。第一个交易日 9:35 后开始积累。</p>
        <table v-else>
          <thead>
            <tr><th>日期</th><th>入选</th><th>平均涨跌</th><th>上涨占比</th><th>名单</th></tr>
          </thead>
          <tbody>
            <tr v-for="d in history" :key="d.date">
              <td>{{ d.date }}</td>
              <td>{{ d.picks.length }} 只</td>
              <td :class="trend(d.avg ?? 0)">{{ d.avg == null ? '—' : signed(d.avg) + '%' }}</td>
              <td>{{ d.win_rate == null ? '—' : d.win_rate + '%' }}</td>
              <td class="names">
                <span v-for="p in d.picks" :key="p.code" :class="trend(p.since_open ?? 0)">
                  {{ p.name }} {{ p.since_open == null ? '' : signed(p.since_open) + '%' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <p class="disclaimer">
        火眼金睛只按公开公告和行情做规则筛选，帮助快速发现值得研究的标的；利好公告不等于股价一定上涨，名单不构成买卖建议。
      </p>
    </div>
  </div>
</template>

<style scoped>
.hawkeye {
  overflow-y: auto;
  font-variant-numeric: tabular-nums;
}
.page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 18px 24px 24px;
}
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}
h1 {
  margin: 0;
  color: var(--navy);
  font-size: 22px;
}
.sub {
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}
.actions {
  display: flex;
  gap: 6px;
}
.card {
  padding: 12px 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}
h2 {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 0 0 10px;
  padding-left: 8px;
  border-left: 3px solid var(--gold);
  color: var(--navy);
  font-size: 15px;
}
h2 span {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 400;
}
.rules {
  margin-bottom: 14px;
}
.rule-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}
.rule-grid h3 {
  margin: 0 0 4px;
  font-size: 13px;
}
.rule-grid ul {
  margin: 0;
  padding-left: 18px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.8;
}
.rule-note {
  margin: 10px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}
.muted {
  color: var(--text-muted);
  font-size: 13px;
}
.error {
  color: var(--danger);
}
.status-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 14px;
  margin-bottom: 12px;
  font-size: 13px;
}
.phase {
  padding: 1px 10px;
  border-radius: 999px;
  background: var(--surface);
  border: 1px solid var(--line-strong);
  font-weight: 600;
}
.phase.live {
  border-color: var(--up);
  color: var(--up);
}

.picks {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 14px;
}
.pick {
  display: grid;
  grid-template-columns: 36px 1fr 180px;
  gap: 14px;
}
.rank {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 6px;
  background: var(--surface-alt);
  color: var(--text-muted);
  font-weight: 700;
}
.rank.top {
  background: var(--navy);
  color: var(--gold);
}
.title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 10px;
}
.name {
  color: var(--navy);
  font-size: 16px;
  font-weight: 600;
  text-decoration: none;
}
.name:hover {
  color: var(--brand);
  text-decoration: underline;
}
.code {
  color: var(--text-muted);
  font-size: 12px;
}
.stars i {
  color: var(--line-strong);
  font-style: normal;
  font-size: 13px;
}
.stars i.on {
  color: var(--gold);
}
.score {
  font-size: 13px;
  font-weight: 600;
}
.score small {
  color: var(--text-muted);
  font-weight: 400;
}
.catalysts {
  margin: 8px 0 6px;
  padding: 0;
  list-style: none;
  font-size: 13px;
}
.catalysts li {
  display: flex;
  align-items: baseline;
  gap: 8px;
  line-height: 1.8;
}
.kind {
  flex-shrink: 0;
  padding: 0 6px;
  border-radius: 3px;
  background: #fdecec;
  color: var(--up);
  font-size: 12px;
  font-weight: 600;
}
.catalysts a {
  min-width: 0;
  overflow: hidden;
  color: var(--text);
  text-decoration: none;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.catalysts a:hover {
  color: var(--brand);
  text-decoration: underline;
}
.date {
  flex-shrink: 0;
  color: var(--text-muted);
  font-size: 12px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip {
  padding: 1px 8px;
  border-radius: 3px;
  font-size: 12px;
}
.chip.good {
  background: var(--brand-soft);
  color: var(--brand);
}
.chip.risk {
  background: #fff4e5;
  color: #a15c00;
}
.warnings {
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
  color: #a15c00;
  font-size: 12px;
}
.warnings a {
  color: inherit;
}
.quote {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  padding-left: 14px;
  border-left: 1px solid var(--line);
}
.price {
  font-size: 22px;
  font-weight: 700;
}
.pct {
  font-size: 13px;
  font-weight: 600;
}
.quote dl {
  display: grid;
  grid-template-columns: 1fr;
  width: 100%;
  margin: 6px 0 8px;
  font-size: 12px;
}
.quote dl div {
  display: flex;
  justify-content: space-between;
}
.quote dt {
  color: var(--text-muted);
}
.quote dd {
  margin: 0;
}
.up {
  color: var(--up);
}
.down {
  color: var(--down);
}
.flat {
  color: var(--text-muted);
}

.history table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.history th {
  padding: 5px 8px;
  border-top: 2px solid var(--navy);
  border-bottom: 1px solid var(--navy);
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 500;
  text-align: left;
}
.history td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
.history td.names {
  white-space: normal;
}
.names span {
  margin-right: 10px;
}
.disclaimer {
  margin: 14px 0 0;
  color: var(--text-muted);
  font-size: 12px;
  text-align: center;
}
</style>
