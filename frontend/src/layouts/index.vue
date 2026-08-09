<template>
  <div class="layout">
    <t-layout class="layout-shell">
      <t-aside class="sidebar" width="248px">
        <div class="brand" aria-label="Grok 管理控制台">
          <span class="brand-mark" aria-hidden="true">/</span>
          <div>
            <strong>grok</strong>
            <span>mirror console</span>
          </div>
        </div>

        <div class="nav-caption">WORKSPACE</div>
        <t-menu class="nav-menu" :value="activeMenu" theme="dark" @change="handleMenuChange">
          <t-menu-item v-if="userStore.isAdmin" value="/account/overview">
            <template #icon><t-icon name="dashboard" /></template>
            <span class="menu-label">运维概览</span>
          </t-menu-item>
          <t-menu-item v-if="userStore.isAdmin" value="/account/user">
            <template #icon><t-icon name="user" /></template>
            <span class="menu-label">用户</span>
          </t-menu-item>
          <t-menu-item v-if="userStore.isAdmin" value="/account/grok">
            <template #icon><t-icon name="root-list" /></template>
            <span class="menu-label">Grok 账号</span>
          </t-menu-item>
          <t-menu-item v-if="userStore.isAdmin" value="/account/grok-pool">
            <template #icon><t-icon name="server" /></template>
            <span class="menu-label">账号池</span>
          </t-menu-item>
          <t-menu-item v-if="userStore.isAdmin" value="/account/logs">
            <template #icon><t-icon name="file" /></template>
            <span class="menu-label">请求日志</span>
          </t-menu-item>
          <t-menu-item v-if="userStore.isAdmin" value="/account/proxy">
            <template #icon><t-icon name="internet" /></template>
            <span class="menu-label">上游代理</span>
          </t-menu-item>
          <t-menu-item v-if="userStore.isAdmin" value="/account/scripts">
            <template #icon><t-icon name="code" /></template>
            <span class="menu-label">注入脚本</span>
          </t-menu-item>
          <t-menu-item v-if="userStore.isAdmin" value="/account/access">
            <template #icon><t-icon name="secured" /></template>
            <span class="menu-label">访问与安全</span>
          </t-menu-item>
          <t-menu-item value="/account/profile">
            <template #icon><t-icon name="user-circle" /></template>
            <span class="menu-label">账户中心</span>
          </t-menu-item>
        </t-menu>

        <div class="sidebar-footer">
          <a href="/" target="_blank" rel="noopener">
            <span class="status-dot" aria-hidden="true"></span>
            打开 Grok 镜像
            <t-icon name="arrow-up-right" />
          </a>
        </div>
      </t-aside>

      <t-layout class="workspace">
        <t-header class="header">
          <div class="title-group">
            <span class="eyebrow">GROK MIRROR</span>
            <h1>{{ pageTitle }}</h1>
          </div>
          <div class="header-right">
            <t-dropdown :options="userOptions" @click="handleUserAction">
              <t-button class="user-button" variant="text">
                <span class="avatar">{{ username.slice(0, 1).toUpperCase() }}</span>
                <span class="username">{{ username }}</span>
                <t-icon name="chevron-down" />
              </t-button>
            </t-dropdown>
          </div>
        </t-header>
        <t-content class="content">
          <div class="content-inner">
            <router-view />
          </div>
        </t-content>
      </t-layout>
    </t-layout>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/store/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const activeMenu = computed(() => route.path)
const username = computed(() => userStore.username || '管理员')
const pageTitle = computed(() => String(route.meta.title || '管理控制台'))

const userOptions = [
  { content: '账户中心', value: 'profile' },
  { content: '退出登录', value: 'logout' }
]

const handleMenuChange = (value: string) => router.push(value)

const handleUserAction = (data: { value: string }) => {
  if (data.value === 'profile') {
    router.push('/account/profile')
    return
  }
  if (data.value === 'logout') {
    userStore.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.layout,
.layout-shell {
  min-height: 100vh;
  min-height: 100dvh;
}

.sidebar {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  height: 100vh;
  height: 100dvh;
  color: #f5f5f4;
  background: #101010;
  border-right: 1px solid #252525;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 78px;
  padding: 0 22px;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  color: #111;
  font-size: 25px;
  font-weight: 800;
  line-height: 1;
  background: #f4f4f2;
  border-radius: 50%;
  transform: rotate(-18deg);
}

.brand div {
  display: grid;
  gap: 1px;
}

.brand strong {
  font-size: 19px;
  font-weight: 650;
  letter-spacing: -0.04em;
}

.brand span:last-child {
  color: #8d8d89;
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.nav-caption {
  padding: 18px 22px 8px;
  color: #656561;
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 0.16em;
}

.nav-menu {
  flex: 1;
  min-height: 0;
  padding: 4px 12px;
  overflow-y: auto;
  background: transparent;
}

.nav-menu :deep(.t-menu__item) {
  height: 42px;
  margin-bottom: 3px;
  color: #aaa9a5;
  border-radius: 9px;
  transition: color 0.2s ease, background 0.2s ease;
}

.nav-menu :deep(.t-menu__item:hover) {
  color: #f4f4f2;
  background: #1c1c1c;
}

.nav-menu :deep(.t-menu__item.t-is-active) {
  color: #111;
  font-weight: 600;
  background: #f2f2ef;
}

.sidebar-footer {
  padding: 12px;
  border-top: 1px solid #292929;
}

.sidebar-footer a {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 44px;
  padding: 0 11px;
  color: #bdbdb9;
  font-size: 13px;
  text-decoration: none;
  border-radius: 9px;
  transition: color 0.2s ease, background 0.2s ease;
}

.sidebar-footer a:hover,
.sidebar-footer a:focus-visible {
  color: #f4f4f2;
  background: #1c1c1c;
  outline: none;
}

.sidebar-footer .t-icon { margin-left: auto; }
.status-dot { width: 7px; height: 7px; background: #73c991; border-radius: 50%; box-shadow: 0 0 0 3px rgba(115, 201, 145, 0.12); }

.workspace {
  min-width: 0;
  background: var(--app-bg);
}

.header {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 78px;
  padding: 0 36px;
  background: rgba(247, 247, 245, 0.92);
  border-bottom: 1px solid var(--app-border);
  backdrop-filter: blur(14px);
}

.title-group { display: grid; gap: 2px; }
.eyebrow { color: #92928d; font-size: 9px; font-weight: 700; letter-spacing: 0.18em; }
.header h1 { margin: 0; color: var(--app-text); font-size: 20px; font-weight: 650; letter-spacing: -0.025em; }
.header-right { display: flex; align-items: center; }

.user-button {
  height: 44px;
  padding: 0 8px;
  color: #50504c;
  border-radius: 10px;
}

.user-button:hover { color: var(--app-text); background: #ecece8; }
.avatar { display: grid; place-items: center; width: 30px; height: 30px; color: #f7f7f5; font-size: 12px; font-weight: 650; background: #1a1a19; border-radius: 50%; }
.username { max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.content {
  min-height: calc(100vh - 78px);
  padding: 34px 36px 56px;
  background: var(--app-bg);
}

.content-inner { width: 100%; max-width: 1380px; margin: 0 auto; }

@media (max-width: 900px) {
  .sidebar { width: 76px !important; flex-basis: 76px !important; }
  .brand { justify-content: center; padding: 0; }
  .brand div, .nav-caption, .menu-label, .sidebar-footer a:not(:focus) { font-size: 0; }
  .nav-menu { padding: 4px 10px; }
  .nav-menu :deep(.t-menu__item) { justify-content: center; padding: 0; }
  .sidebar-footer a { justify-content: center; padding: 0; }
  .sidebar-footer .t-icon, .sidebar-footer .status-dot { display: none; }
  .header { padding: 0 22px; }
  .content { padding: 24px 20px 42px; }
}

@media (max-width: 560px) {
  .sidebar { width: 60px !important; flex-basis: 60px !important; }
  .brand-mark { width: 32px; height: 32px; }
  .nav-menu { padding: 4px 7px; }
  .header { height: 70px; padding: 0 16px; }
  .eyebrow, .username { display: none; }
  .header h1 { font-size: 17px; }
  .content { min-height: calc(100vh - 70px); padding: 18px 12px 36px; }
}
</style>
