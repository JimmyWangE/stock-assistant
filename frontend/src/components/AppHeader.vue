<script setup lang="ts">
import {
  Aim,
  ArrowDown,
  ChatLineSquare,
  DataBoard,
  Document,
  Star,
  SwitchButton,
} from '@element-plus/icons-vue'

import { currentUser } from '../auth'
import { board, openIndex, signed, trend } from '../market'
import AlertBell from './AlertBell.vue'
import BrandMark from './BrandMark.vue'
import StockSearch from './StockSearch.vue'

defineEmits<{ logout: [] }>()
</script>

<template>
  <header class="app-header">
    <div class="brand">
      <BrandMark :size="28" />
      <div>
        <div class="brand-name">A股投研助手</div>
        <div class="brand-sub">EQUITY RESEARCH</div>
      </div>
    </div>

    <nav class="tabs">
      <router-link to="/" class="tab" exact-active-class="active">
        <el-icon><DataBoard /></el-icon>市场概览
      </router-link>
      <router-link
        to="/chat"
        class="tab"
        :class="{ active: $route.name === 'new-chat' || $route.name === 'chat' }"
      >
        <el-icon><ChatLineSquare /></el-icon>智能投研
      </router-link>
      <router-link to="/watchlist" class="tab" active-class="active">
        <el-icon><Star /></el-icon>自选股
      </router-link>
      <router-link to="/hawkeye" class="tab" active-class="active">
        <el-icon><Aim /></el-icon>火眼金睛
      </router-link>
      <router-link to="/reports" class="tab" active-class="active">
        <el-icon><Document /></el-icon>每日报告
      </router-link>
    </nav>

    <!-- 指数行情条：点击查看分时和日 K。放不下的指数整个不显示，不会截断数字 -->
    <ul v-if="board?.indices.length" class="ticker">
      <li v-for="item in board.indices.slice(0, 5)" :key="item.code" :class="trend(item.change)">
        <button type="button" :title="`查看${item.name}分时与日 K`" @click="openIndex(item.code)">
          <span class="name">{{ item.name }}</span>
          <span class="price">{{ item.price.toFixed(2) }}</span>
          <span class="change">{{ signed(item.change) }}</span>
          <span class="change">{{ signed(item.percent) }}%</span>
        </button>
      </li>
    </ul>
    <div v-else class="ticker" />

    <div class="right">
      <StockSearch />
      <span v-if="board?.session" class="session" :class="{ open: board.session === '交易中' }">
        <span class="dot" />{{ board.session }}
      </span>
      <AlertBell />
      <el-dropdown trigger="click" @command="$emit('logout')">
        <button type="button" class="user">
          <span class="avatar" aria-hidden="true">{{
            currentUser?.username.slice(0, 1).toUpperCase()
          }}</span>
          <span class="username">{{ currentUser?.username }}</span>
          <el-icon><ArrowDown /></el-icon>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item :icon="SwitchButton" command="logout">退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  display: flex;
  align-items: center;
  gap: 20px;
  height: 52px;
  flex-shrink: 0;
  padding: 0 16px 0 18px;
  background: var(--navy);
  color: var(--on-navy);
  white-space: nowrap;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
  color: #fff;
}
.brand-name {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.3;
  letter-spacing: 0.5px;
}
.brand-sub {
  color: var(--gold);
  font-size: 10px;
  line-height: 1.3;
  letter-spacing: 2px;
}
.ticker {
  display: flex;
  flex: 1;
  flex-wrap: wrap;
  height: 52px;
  min-width: 0;
  margin: 0;
  padding: 0;
  list-style: none;
  overflow: hidden;
}
.ticker li {
  height: 52px;
  padding-right: 6px;
}
.ticker button {
  display: flex;
  align-items: baseline;
  gap: 7px;
  height: 36px;
  margin-top: 8px;
  padding: 0 10px;
  border: 0;
  border-radius: 6px;
  background: none;
  color: inherit;
  font: inherit;
  font-size: 13px;
  line-height: 36px;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
}
.ticker button:hover,
.ticker button:focus-visible {
  background: var(--navy-soft);
  outline: none;
}
.tabs {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}
.tab {
  display: flex;
  align-items: center;
  gap: 5px;
  height: 52px;
  padding: 0 10px;
  border-bottom: 2px solid transparent;
  box-sizing: border-box;
  color: var(--on-navy-muted);
  font-size: 14px;
  text-decoration: none;
}
.tab:hover {
  color: #fff;
}
.tab.active {
  border-bottom-color: var(--gold);
  color: #fff;
  font-weight: 600;
}
.name {
  color: var(--on-navy-muted);
}
.price {
  font-weight: 600;
}
.change {
  font-size: 12px;
}
/* 深色背景上用更亮的红绿，保证对比度 */
.up .price,
.up .change {
  color: #ff6b6b;
}
.down .price,
.down .change {
  color: #3ecf8e;
}
.right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.session {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  border: 1px solid var(--navy-line);
  border-radius: 999px;
  color: var(--on-navy-muted);
  font-size: 12px;
}
.session .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--on-navy-muted);
}
.session.open {
  color: var(--on-navy);
}
.session.open .dot {
  background: #3ecf8e;
}
.user {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 34px;
  padding: 0 8px;
  border: 0;
  border-radius: 6px;
  background: none;
  color: var(--on-navy);
  font: inherit;
  font-size: 14px;
  cursor: pointer;
}
.user:hover,
.user:focus-visible {
  background: var(--navy-soft);
  outline: none;
}
.avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--gold);
  color: var(--navy);
  font-size: 12px;
  font-weight: 700;
}
/* 窄屏时只留头像，给指数行情条让出位置 */
@media (max-width: 1360px) {
  .username,
  .session {
    display: none;
  }
}
.username {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
