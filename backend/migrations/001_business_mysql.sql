-- Wedding AI Tool business database schema.
-- Run this in the tool business database. Do not run it in the user-center database.
-- Secrets must stay in environment variables, never in this file.

CREATE TABLE IF NOT EXISTS storage_meta (
  `key` VARCHAR(191) PRIMARY KEY,
  `value` TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS terminal_user_binding (
  id INT PRIMARY KEY AUTO_INCREMENT,
  tenant_id VARCHAR(64) NOT NULL,
  platform_user_id VARCHAR(64) NOT NULL,
  local_user_id VARCHAR(64) NOT NULL,
  app_code VARCHAR(64) NOT NULL DEFAULT 'wedding_ai_tool',
  roles_json TEXT NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'active',
  created_at VARCHAR(32) NOT NULL,
  updated_at VARCHAR(32) NOT NULL,
  UNIQUE KEY uk_tenant_platform_user (tenant_id, platform_user_id),
  KEY idx_terminal_user_binding_local (local_user_id),
  KEY idx_terminal_user_binding_tenant_status (tenant_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS tool_sessions (
  session_id VARCHAR(64) PRIMARY KEY,
  tenant_id VARCHAR(64) NOT NULL,
  platform_user_id VARCHAR(64) NOT NULL,
  local_user_id VARCHAR(64) NOT NULL,
  username VARCHAR(128) NOT NULL DEFAULT '',
  app_code VARCHAR(64) NOT NULL DEFAULT 'wedding_ai_tool',
  roles_json TEXT NOT NULL,
  expires_at BIGINT NOT NULL,
  revoked_at VARCHAR(32) NOT NULL DEFAULT '',
  created_at VARCHAR(32) NOT NULL,
  updated_at VARCHAR(32) NOT NULL,
  KEY idx_tool_sessions_identity (tenant_id, platform_user_id),
  KEY idx_tool_sessions_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS tasks (
  task_id VARCHAR(64) PRIMARY KEY,
  tenant_id VARCHAR(64) NOT NULL DEFAULT 'dev',
  platform_user_id VARCHAR(64) NOT NULL DEFAULT 'dev',
  local_user_id VARCHAR(64) NOT NULL DEFAULT 'dev',
  app_code VARCHAR(64) NOT NULL DEFAULT 'wedding_ai_tool',
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  record_json TEXT NOT NULL,
  created_at VARCHAR(32) NOT NULL DEFAULT '',
  updated_at VARCHAR(32) NOT NULL,
  KEY idx_tasks_tenant_created (tenant_id, created_at),
  KEY idx_tasks_user_created (tenant_id, platform_user_id, created_at),
  KEY idx_tasks_status_created (tenant_id, status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS assets (
  asset_id VARCHAR(64) PRIMARY KEY,
  tenant_id VARCHAR(64) NOT NULL DEFAULT 'dev',
  platform_user_id VARCHAR(64) NOT NULL DEFAULT 'dev',
  local_user_id VARCHAR(64) NOT NULL DEFAULT 'dev',
  category VARCHAR(32) NOT NULL DEFAULT 'uncategorized',
  file_id VARCHAR(255) NOT NULL DEFAULT '',
  filename VARCHAR(255) NOT NULL DEFAULT '',
  visibility VARCHAR(16) NOT NULL DEFAULT 'personal',
  deleted_at VARCHAR(32) NOT NULL DEFAULT '',
  record_json TEXT NOT NULL,
  created_at VARCHAR(32) NOT NULL DEFAULT '',
  updated_at VARCHAR(32) NOT NULL,
  KEY idx_assets_tenant_category (tenant_id, category, created_at),
  KEY idx_assets_tenant_user (tenant_id, platform_user_id, created_at),
  KEY idx_assets_file_category (tenant_id, file_id, category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS quality_reviews (
  id INT PRIMARY KEY AUTO_INCREMENT,
  tenant_id VARCHAR(64) NOT NULL DEFAULT 'dev',
  platform_user_id VARCHAR(64) NOT NULL DEFAULT 'dev',
  local_user_id VARCHAR(64) NOT NULL DEFAULT 'dev',
  task_id VARCHAR(64) NOT NULL,
  record_json TEXT NOT NULL,
  created_at VARCHAR(32) NOT NULL DEFAULT '',
  updated_at VARCHAR(32) NOT NULL,
  UNIQUE KEY uk_quality_review_tenant_task (tenant_id, task_id),
  KEY idx_quality_reviews_tenant_updated (tenant_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS business_logs (
  id INT PRIMARY KEY AUTO_INCREMENT,
  tenant_id VARCHAR(64) NOT NULL DEFAULT 'dev',
  platform_user_id VARCHAR(64) NOT NULL DEFAULT 'dev',
  local_user_id VARCHAR(64) NOT NULL DEFAULT 'dev',
  trace_id VARCHAR(64) NOT NULL DEFAULT '',
  action VARCHAR(64) NOT NULL,
  resource_type VARCHAR(64) NOT NULL DEFAULT '',
  resource_id VARCHAR(128) NOT NULL DEFAULT '',
  record_json TEXT NOT NULL,
  created_at VARCHAR(32) NOT NULL,
  KEY idx_business_logs_tenant_created (tenant_id, created_at),
  KEY idx_business_logs_trace (trace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
