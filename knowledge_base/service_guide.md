# Sample Knowledge Base — Service Configuration Guide

This directory contains example documentation for a fictional microservice.

## Architecture Overview

The system consists of three services:

1. **api-gateway** — receives external HTTP requests, handles auth, routes to backend services
2. **user-service** — manages user accounts, profiles, and permissions
3. **order-service** — processes orders, manages inventory, publishes events

Services communicate over gRPC. The gateway authenticates via JWT tokens and proxies requests.

## Service Ports

| Service | HTTP Port | gRPC Port | Health Check |
|---------|-----------|-----------|--------------|
| api-gateway | 8080 | 9090 | /healthz |
| user-service | 8081 | 9091 | /healthz |
| order-service | 8082 | 9092 | /healthz |

## Environment Variables

### api-gateway

| Variable | Default | Description |
|----------|---------|-------------|
| `GATEWAY_PORT` | `8080` | HTTP listen port |
| `GRPC_PORT` | `9090` | gRPC listen port |
| `JWT_SECRET` | *required* | Secret for JWT token verification |
| `JWT_EXPIRY_MINUTES` | `60` | Token expiry in minutes |
| `USER_SERVICE_ADDR` | `localhost:9091` | user-service gRPC address |
| `ORDER_SERVICE_ADDR` | `localhost:9092` | order-service gRPC address |
| `LOG_LEVEL` | `info` | Log level: debug, info, warn, error |
| `RATE_LIMIT_RPS` | `100` | Max requests per second per client |

### user-service

| Variable | Default | Description |
|----------|---------|-------------|
| `USER_SERVICE_PORT` | `8081` | HTTP listen port |
| `GRPC_PORT` | `9091` | gRPC listen port |
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_NAME` | `users` | Database name |
| `DB_USER` | `postgres` | Database user |
| `DB_PASSWORD` | *required* | Database password |
| `DB_MAX_CONNECTIONS` | `20` | Connection pool size |
| `REDIS_HOST` | `localhost` | Redis host for caching |
| `REDIS_PORT` | `6379` | Redis port |

### order-service

| Variable | Default | Description |
|----------|---------|-------------|
| `ORDER_SERVICE_PORT` | `8082` | HTTP listen port |
| `GRPC_PORT` | `9092` | gRPC listen port |
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_NAME` | `orders` | Database name |
| `DB_USER` | `postgres` | Database user |
| `DB_PASSWORD` | *required* | Database password |
| `INVENTORY_CHECK_ENABLED` | `true` | Whether to check inventory before order |

## Common Error Codes

### api-gateway

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `GW-001` | 401 | Missing or invalid JWT token |
| `GW-002` | 403 | Token valid but insufficient permissions |
| `GW-003` | 429 | Rate limit exceeded |
| `GW-004` | 502 | Upstream service unreachable |
| `GW-005` | 504 | Upstream service timeout |

### user-service

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `US-001` | 404 | User not found |
| `US-002` | 409 | Email already registered |
| `US-003` | 400 | Invalid user input |
| `US-004` | 503 | Database connection failed |
| `US-005` | 503 | Redis connection failed |

### order-service

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `OS-001` | 404 | Order not found |
| `OS-002` | 400 | Insufficient inventory |
| `OS-003` | 400 | Invalid order state transition |
| `OS-004` | 503 | Database connection failed |

## Troubleshooting Guides

### GW-004: Upstream Service Unreachable

This error occurs when the api-gateway cannot connect to a backend service.

**Common causes:**
1. Backend service is not running
2. Wrong gRPC address configured
3. Network firewall blocking the port
4. Service crashed due to OOM

**Diagnosis steps:**
1. Check if the backend service process is running
2. Verify the gRPC address env var (USER_SERVICE_ADDR / ORDER_SERVICE_ADDR) matches the actual service address
3. Try `telnet <host> <grpc_port>` to test connectivity
4. Check backend service logs for crash or startup errors
5. Verify DNS resolution if using hostnames

### US-004: Database Connection Failed

This error means the user-service cannot connect to its PostgreSQL database.

**Common causes:**
1. PostgreSQL is not running
2. Wrong DB_HOST / DB_PORT configuration
3. Authentication failure (wrong password or user)
4. Connection pool exhausted (DB_MAX_CONNECTIONS too low)
5. Network partition between service and database

**Diagnosis steps:**
1. Verify PostgreSQL is running: `systemctl status postgresql`
2. Check connectivity: `psql -h <DB_HOST> -p <DB_PORT> -U <DB_USER> -d <DB_NAME>`
3. Check active connections: `SELECT count(*) FROM pg_stat_activity;`
4. Review service logs for connection errors
5. Check DB_MAX_CONNECTIONS setting against actual pool usage

### Rate Limiting (GW-003)

When clients exceed RATE_LIMIT_RPS, the gateway returns 429 with a `Retry-After` header.

**Configuration:**
- Set `RATE_LIMIT_RPS` to adjust the per-client limit (default 100)
- Rate limiting uses a sliding window algorithm with Redis
- If Redis is unavailable, rate limiting falls back to local in-memory counting

## Deployment Checklist

Before deploying to production, verify:

- [ ] All required environment variables are set (especially JWT_SECRET, DB_PASSWORD)
- [ ] Database migrations have been applied
- [ ] Health check endpoints return 200
- [ ] gRPC ports are reachable between services
- [ ] TLS certificates are valid and not expiring within 30 days
- [ ] Log aggregation is configured
- [ ] Monitoring alerts are set up for error code spikes
- [ ] Rate limits are tuned for expected traffic
