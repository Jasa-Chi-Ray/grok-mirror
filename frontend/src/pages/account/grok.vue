<template>
  <div>
    <t-card title="上游账号" subtitle="维护账号凭证、登录模式和连接状态" :bordered="false">
      <template #actions>
        <t-space>
          <t-button :loading="checkingAll" @click="handleCheckTokenExpiry()">
            <template #icon><t-icon name="search" /></template>
            一键检测
          </t-button>
          <t-button theme="primary" @click="showAddDialog">
            <template #icon><t-icon name="add" /></template>
            添加账号
          </t-button>
        </t-space>
      </template>
      <div class="account-toolbar">
        <t-input v-model="query" clearable placeholder="搜索上游账号" @enter="applyFilters" />
        <t-select v-model="statusFilter" clearable placeholder="全部状态" @change="applyFilters">
          <t-option value="healthy" label="健康" />
          <t-option value="unhealthy" label="异常" />
        </t-select>
        <t-button variant="outline" @click="applyFilters">查询</t-button>
      </div>

      <t-table
        :data="tableData"
        :columns="columns"
        :loading="loading"
        :pagination="pagination"
        @page-change="onPageChange"
        row-key="id"
      >
        <template #auth_status="{ row }">
          <t-tag :theme="row.auth_status ? 'success' : 'danger'">
            {{ row.auth_status ? '有效' : '已过期' }}
          </t-tag>
        </template>
        <template #plan_type="{ row }">
          <t-tag :theme="getPlanTheme(row.plan_type)">
            {{ row.plan_type }}
          </t-tag>
        </template>
        <template #use_count="{ row }">
          <t-space size="small">
            <span>1h: {{ row.use_count?.last_1h || 0 }}</span>
            <span>2h: {{ row.use_count?.last_2h || 0 }}</span>
            <span>3h: {{ row.use_count?.last_3h || 0 }}</span>
          </t-space>
        </template>
        <template #has_sso="{ row }">
          <t-tag :theme="row.session_token_valid ? 'success' : row.has_sso ? 'warning' : 'default'" variant="light">
            {{ row.session_token_valid ? '有效' : row.has_sso ? '待验证/不可用' : '未配置' }}
          </t-tag>
        </template>
        <template #last_check_at="{ row }">
          <span>{{ formatCheckTime(row.last_check_at) }}</span>
        </template>
        <template #proxy_node_id="{ row }">
          <t-tag :theme="row.proxy_node_id ? 'primary' : 'default'" variant="light">
            {{ row.proxy_node_id ? `节点 ${row.proxy_node_id}` : '直连' }}
          </t-tag>
        </template>
        <template #sso_remaining="{ row }">
          <t-tag :theme="getSsoRemainingTheme(row)" variant="light">
            {{ formatSsoRemaining(row) }}
          </t-tag>
        </template>
        <template #last_error="{ row }">
          <span>{{ row.last_error || '-' }}</span>
        </template>
        <template #op="{ row }">
          <t-space>
            <t-link theme="primary" :loading="checkingId === row.id" @click="handleCheckTokenExpiry(row)">
              检测
            </t-link>
            <t-link theme="primary" @click="showEditDialog(row)">编辑</t-link>
            <t-popconfirm content="确定删除该账号吗？" @confirm="handleDelete(row)">
              <t-link theme="danger">删除</t-link>
            </t-popconfirm>
          </t-space>
        </template>
      </t-table>
    </t-card>

    <!-- 添加对话框 -->
    <t-dialog
      :visible="addDialogVisible"
      header="添加上游账号"
      :confirm-btn="{ loading: submitLoading }"
      @confirm="handleAdd"
      @close="addDialogVisible = false"
      width="600px"
    >
      <t-form :data="addFormData" ref="addFormRef" label-width="120px">
        <t-form-item label="SSO Cookie" name="sso">
          <t-textarea
            v-model="addFormData.sso"
            autocomplete="new-password"
            placeholder="仅支持 SSOcookie"
            :autosize="{ minRows: 4, maxRows: 8 }"
          />
        </t-form-item>
        <t-form-item>
          <t-alert theme="info" message="系统会验证 SSO 并自动识别账号；凭据由后端加密保存。" />
        </t-form-item>
      </t-form>
    </t-dialog>

    <!-- 编辑对话框 -->
    <t-dialog
      :visible="editDialogVisible"
      header="编辑上游账号"
      :confirm-btn="{ loading: submitLoading }"
      @confirm="handleEdit"
      @close="editDialogVisible = false"
    >
      <t-form :data="editFormData" ref="editFormRef" label-width="100px">
        <t-form-item label="账号">
          <t-input :value="editFormData.grok_username" disabled />
        </t-form-item>
        <t-form-item label="备注" name="remark">
          <t-textarea v-model="editFormData.remark" placeholder="请输入备注" />
        </t-form-item>
        <t-form-item label="代理节点" name="proxy_node_id">
          <t-select v-model="editFormData.proxy_node_id" clearable placeholder="不绑定节点则直连">
            <t-option
              v-for="node in proxyNodeOptions"
              :key="node.id"
              :value="node.id"
              :label="`节点 ${node.id}`"
            />
          </t-select>
        </t-form-item>
        <t-form-item label="替换 sso" name="sso">
          <t-textarea
            v-model="editFormData.sso"
            autocomplete="new-password"
            placeholder="留空表示保持现有 SSO；建议粘贴带过期字段的 Cookie"
            :autosize="{ minRows: 3, maxRows: 6 }"
          />
        </t-form-item>
      </t-form>
    </t-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import request from '@/api/request'

const loading = ref(false)
const submitLoading = ref(false)
const addDialogVisible = ref(false)
const editDialogVisible = ref(false)
const addFormRef = ref()
const editFormRef = ref()
const tableData = ref<any[]>([])
const proxyNodeOptions = ref<Array<{ id: number }>>([])
const checkingAll = ref(false)
const checkingId = ref<number | null>(null)
const nowSeconds = ref(Math.floor(Date.now() / 1000))
const query = ref('')
const statusFilter = ref('')

const pagination = reactive({
  current: 1,
  pageSize: 10,
  total: 0
})

const columns = [
  { colKey: 'id', title: 'ID', width: 80 },
  { colKey: 'grok_username', title: '账号', ellipsis: true },
  { colKey: 'plan_type', title: '套餐', cell: 'plan_type', width: 100 },
  { colKey: 'auth_status', title: '状态', cell: 'auth_status', width: 100 },
  { colKey: 'has_sso', title: 'SSO 状态', cell: 'has_sso', width: 140 },
  { colKey: 'use_count', title: '使用次数', cell: 'use_count', width: 200 },
  { colKey: 'proxy_node_id', title: '代理节点', cell: 'proxy_node_id', width: 110 },
  { colKey: 'sso_remaining', title: 'SSO 剩余', cell: 'sso_remaining', width: 160 },
  { colKey: 'last_check_at', title: '最近诊断', cell: 'last_check_at', width: 160 },
  { colKey: 'last_error', title: '诊断结果', cell: 'last_error', ellipsis: true },
  { colKey: 'remark', title: '备注', ellipsis: true },
  { colKey: 'op', title: '操作', cell: 'op', width: 200 }
]

const addFormData = reactive({
  sso: ''
})

const editFormData = reactive({
  grok_username: '',
  remark: '',
  proxy_node_id: null as number | null,
  sso: ''
})

onMounted(() => {
  fetchData()
  fetchProxyNodes()
})

const formatCheckTime = (value?: number | null) => {
  if (!value) return '-'
  const date = new Date(value * 1000)
  const yyyy = date.getFullYear()
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  const hh = String(date.getHours()).padStart(2, '0')
  const mi = String(date.getMinutes()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`
}

const getPlanTheme = (planType?: string) => {
  const normalized = (planType || '').toLowerCase()
  if (['team', 'business', 'enterprise', 'workspace'].includes(normalized)) {
    return 'warning'
  }
  if (['plus', 'pro'].includes(normalized)) {
    return 'primary'
  }
  return 'default'
}

const secondsUntilSsoExpiry = (row: any) => {
  if (!row?.sso_exp) return null
  return Number(row.sso_exp) - nowSeconds.value
}

const formatSeconds = (seconds: number | null) => {
  if (seconds === null || Number.isNaN(seconds)) return '-'
  if (seconds <= 0) return '已过期'
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days > 0) return `${days}天${hours}小时`
  if (hours > 0) return `${hours}小时${minutes}分钟`
  return `${Math.max(minutes, 1)}分钟`
}

const formatSsoRemaining = (row: any) => {
  const seconds = secondsUntilSsoExpiry(row)
  return seconds === null ? '上游未返回到期时间' : formatSeconds(seconds)
}

const getSsoRemainingTheme = (row: any) => {
  const seconds = secondsUntilSsoExpiry(row)
  if (seconds === null) return 'default'
  if (seconds <= 0) return 'danger'
  if (seconds < 86400) return 'warning'
  return 'success'
}

const fetchData = async () => {
  loading.value = true
  const params = new URLSearchParams({
    page: String(pagination.current),
    page_size: String(pagination.pageSize)
  })
  if (query.value.trim()) params.set('q', query.value.trim())
  if (statusFilter.value) params.set('status', statusFilter.value)
  const data = await request(`/0x/grok?${params.toString()}`)
  loading.value = false
  
  if (data) {
    nowSeconds.value = Math.floor(Date.now() / 1000)
    tableData.value = data.results || []
    pagination.total = data.count || 0
  }
}

const applyFilters = () => {
  pagination.current = 1
  fetchData()
}

const fetchProxyNodes = async () => {
  const data = await request('/0x/user/proxy-config')
  if (data) {
    proxyNodeOptions.value = (data.nodes || [])
      .filter((node: any) => node.enabled)
      .map((node: any) => ({ id: Number(node.id) }))
      .filter((node: any) => node.id > 0)
  }
}

const onPageChange = (pageInfo: any) => {
  pagination.current = pageInfo.current
  pagination.pageSize = pageInfo.pageSize
  fetchData()
}

const showAddDialog = () => {
  addFormData.sso = ''
  addDialogVisible.value = true
}

const showEditDialog = (row: any) => {
  editFormData.grok_username = row.grok_username
  editFormData.remark = row.remark || ''
  editFormData.proxy_node_id = row.proxy_node_id || null
  editFormData.sso = ''
  editDialogVisible.value = true
}

const handleAdd = async () => {
  const sso = addFormData.sso.trim()
  if (!sso) {
    MessagePlugin.warning('请输入 SSO Cookie')
    return
  }
  submitLoading.value = true
  const data = await request('/0x/grok', 'POST', {
    sso
  })
  submitLoading.value = false

  if (data) {
    MessagePlugin.success(data.message || 'SSO 账号录入成功')
    addDialogVisible.value = false
    fetchData()
  }
}

const handleEdit = async () => {
  submitLoading.value = true
  const payload: Record<string, unknown> = {
    ...editFormData,
    proxy_node_id: editFormData.proxy_node_id || null
  }
  if (!editFormData.sso.trim()) delete payload.sso
  const data = await request('/0x/grok', 'PUT', payload)
  submitLoading.value = false

  if (data) {
    MessagePlugin.success('更新成功')
    editDialogVisible.value = false
    fetchData()
  }
}

const mergeTokenCheckResults = (results: any[]) => {
  nowSeconds.value = Math.floor(Date.now() / 1000)
  const resultMap = new Map(results.map(item => [item.id, item]))
  tableData.value = tableData.value.map(row => {
    const result = resultMap.get(row.id)
    return result ? { ...row, ...result } : row
  })
}

const summarizeTokenCheck = (results: any[]) => {
  if (results.length === 0) return '没有可检测的账号'
  if (results.length === 1) {
    const remaining = results[0].remaining_seconds
    return `SSO 剩余：${remaining === null ? '上游未返回到期时间' : formatSeconds(remaining)}`
  }
  const expiredCount = results.filter(item => item.expired === true).length
  return `检测完成：${results.length}个账号，已过期${expiredCount}个`
}

const handleCheckTokenExpiry = async (row?: any) => {
  const ids = row ? [row.id] : tableData.value.map(item => item.id)
  if (ids.length === 0) {
    MessagePlugin.warning('当前页没有账号')
    return
  }

  if (row) {
    checkingId.value = row.id
  } else {
    checkingAll.value = true
  }

  const data = await request('/0x/grok/token-expiry', 'POST', row ? { ids } : {})

  if (row) {
    checkingId.value = null
  } else {
    checkingAll.value = false
  }

  if (data?.results) {
    mergeTokenCheckResults(data.results)
    MessagePlugin.success(summarizeTokenCheck(data.results))
  }
}

const handleDelete = async (row: any) => {
  const data = await request('/0x/grok', 'DELETE', {
    grok_username: row.grok_username
  })
  if (data) {
    MessagePlugin.success('删除成功')
    fetchData()
  }
}
</script>

<style scoped>
.account-toolbar {
  display: grid;
  grid-template-columns: minmax(240px, 1fr) 180px auto;
  gap: 10px;
  margin-bottom: 16px;
}
</style>
