<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '../api'
import { setUser } from '../auth'
import AppHeader from '../components/AppHeader.vue'
import IndexDrawer from '../components/IndexDrawer.vue'
import { startBoard, stopBoard } from '../market'

const router = useRouter()

async function logout(): Promise<void> {
  try {
    await api.logout()
  } finally {
    setUser(null)
    router.replace({ name: 'login' })
  }
}

onMounted(startBoard)
onBeforeUnmount(stopBoard)
</script>

<template>
  <div class="shell">
    <AppHeader @logout="logout" />
    <div class="content">
      <router-view />
    </div>
    <IndexDrawer />
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 760px;
  background: var(--surface-alt);
}
.content {
  display: flex;
  flex: 1;
  min-height: 0;
}
.content > :deep(*) {
  flex: 1;
  min-width: 0;
}
</style>
