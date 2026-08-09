<template>
  <div>
    <div v-if="!tableVisible" class="login-grok-state">
      <t-loading :loading="tableLoading" size="medium">
        <div class="login-grok-card">
          <div class="login-grok-title">正在准备会话</div>
          <div class="login-grok-desc">{{ statusText }}</div>
        </div>
      </t-loading>
    </div>
    <t-dialog
      :visible="tableVisible"
      header="请选择可用账号"
      :cancel-btn="null"
      :confirm-btn="null"
      :on-close="onClose"
      width="930px"
    >
      <t-loading :loading="tableLoading">
        <t-space direction="vertical" style="width: 100%; margin-bottom: 16px" :size="12">
          <t-space>
            <t-button theme="primary" :disabled="tableLoading" @click="onSelect(null)">
              智能分配最空闲账号
            </t-button>
            <t-button variant="text" @click="router.push('/account/profile')">账户中心</t-button>
          </t-space>
          <t-alert theme="info" message="账号通过 SSO 建立网页会话。" />
        </t-space>
        <t-space break-line>
          <div
            v-for="item in tableData"
            :key="item.id"
            style="width: 160px; cursor: pointer"
            :class="{ 'is-disabled': !item.auth_status || !supportsMode(item) }"
            @click="onSelect(item.id)"
          >
            <div style="background: #f2f4f7; padding: 8px; border-radius: 5px">
              <t-space direction="vertical" style="width: 100%" :size="8">
                <div>
                  <div style="display: flex; justify-content: space-between">
                    <t-tag
                      size="small"
                      theme="primary"
                      variant="outline"
                      style="width: 35px"
                      :class="{ 'shiny-blue': item.plan_type !== 'free' }"
                    >{{ item.plan_type }}</t-tag>
                    <span>{{ item.grok_flag }}</span>
                  </div>
                </div>

                <div class="mode-tags">
                  <t-tag size="small" :theme="item.session_token_valid ? 'success' : 'default'">
                    SSO
                  </t-tag>
                </div>

                <div style="font-size: 12px; display: flex; justify-content: space-between">
                  <div>实时状态</div>
                  <div>
                    <span v-if="item.auth_status === false">已过期</span>
                    <span v-else-if="getGrokUsePercent(item) < 40">空闲</span>
                    <span v-else-if="getGrokUsePercent(item) < 80">忙碌</span>
                    <span v-else>繁忙 | 可用</span>
                  </div>
                </div>

                <div>
                  <t-progress
                    v-if="getGrokUsePercent(item) < 40"
                    :percentage="getGrokUsePercent(item)"
                    status="success"
                    :label="false"
                  />
                  <t-progress
                    v-else-if="getGrokUsePercent(item) < 80"
                    :percentage="getGrokUsePercent(item)"
                    status="warning"
                    :label="false"
                  />
                  <t-progress v-else :percentage="getGrokUsePercent(item)" status="error" :label="false" />
                </div>
              </t-space>
            </div>
          </div>
        </t-space>
      </t-loading>
    </t-dialog>
  </div>
</template>

<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next'
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import request from '@/api/request'
import { useUserStore } from '@/store/user'

const tableLoading = ref(false)
const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const tableVisible = ref(false)
const statusText = ref('正在加载可用账号...')

interface TableData {
  id: number
  grok_flag: string
  plan_type: string
  auth_status: boolean
  use_count: number
  session_token_valid: boolean
  supported_login_modes: string[]
}
const tableData = ref<TableData[]>([])

onMounted(async () => {
  if (route.query.logout === '1') {
    userStore.logout()
  }
  await getUserGrokAccountList()
})

const getGrokUsePercent = (item: TableData) => {
  const MaxLimitCount = item.plan_type === 'free' ? 20 : 80
  return Math.min((item.use_count / MaxLimitCount) * 100 + 1, 99)
}

const getUserGrokAccountList = async () => {
  tableLoading.value = true
  statusText.value = '正在加载可用账号...'
  const data = await request('/0x/user/grok-list')
  tableLoading.value = false
  
  if (!data) {
    router.push({ name: 'Login' })
    return
  }
  
  const results = data.results || []
  tableData.value = results

  if (results.length === 0) {
    MessagePlugin.warning('暂无可用账号，请联系管理员添加')
    statusText.value = '暂无可用账号，请联系管理员添加'
  } else {
    if (results.length === 1 && results[0].auth_status && !supportsMode(results[0])) {
      statusText.value = '该账号的 SSO 当前不可用，请联系管理员更新'
    }
    tableVisible.value = true
  }
}

const onClose = () => {
  router.push({ name: 'Login' })
}

const supportsMode = (item: TableData) => {
  return Array.isArray(item.supported_login_modes) && item.supported_login_modes.includes('web')
}

const onSelect = async (grokId: number | null) => {
  const current = tableData.value.find(item => item.id === grokId)
  if (current && !supportsMode(current)) {
    MessagePlugin.warning('该账号的 SSO 当前不可用，请联系管理员更新')
    return
  }

  tableLoading.value = true
  statusText.value = '正在建立会话，请稍候...'
  const data = await request('/0x/grok/login', 'POST', {
    grok_id: grokId,
    login_mode: 'web',
  })
  tableLoading.value = false
  
  if (data) {
    MessagePlugin.success('登录成功')
    if (data.login_url) {
      window.location.replace(data.login_url)
      return
    }
  }

  if (!tableVisible.value) {
    statusText.value = '登录失败，请返回重试'
  }
}
</script>

<style scoped>
.login-grok-state {
  min-height: 70vh;
  display: flex;
  align-items: center;
  justify-content: center;
}

.login-grok-card {
  min-width: 320px;
  padding: 24px 28px;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 12px 40px rgba(15, 23, 42, 0.08);
  text-align: center;
}

.login-grok-title {
  font-size: 20px;
  font-weight: 600;
  color: #111827;
}

.login-grok-desc {
  margin-top: 10px;
  color: #6b7280;
  font-size: 14px;
}

.mode-switch {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.mode-switch__label {
  color: #111827;
  font-size: 14px;
  font-weight: 600;
}

.mode-tags {
  display: flex;
  gap: 6px;
}

.is-disabled {
  opacity: 0.5;
  pointer-events: none;
}

.shiny-blue {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
}
</style>
