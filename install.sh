#!/usr/bin/env bash

set -Eeuo pipefail

readonly SQUID_CONFIG='/etc/squid/squid.conf'
readonly SQUID_PORT='18889'
readonly SQUID_PID='/run/squid/squid.pid'

if [[ ${EUID} -ne 0 ]]; then
    exec sudo "$0" "$@"
fi

export DEBIAN_FRONTEND=noninteractive

has_systemd() {
    [[ -d /run/systemd/system ]] && systemctl is-system-running >/dev/null 2>&1
}

is_listening() {
    ss -lnt | awk '{print $4}' | grep -q ":${SQUID_PORT}$"
}

has_live_squid() {
    [[ -f ${SQUID_PID} ]] || return 1

    local pid
    read -r pid < "$SQUID_PID" || return 1
    [[ ${pid} =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null
}

wait_for_listening() {
    for _ in {1..10}; do
        if is_listening; then
            return 0
        fi
        sleep 1
    done
    return 1
}

wait_for_stop() {
    local pid=$1
    for _ in {1..40}; do
        if ! kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
        sleep 1
    done
    return 1
}

install_and_configure() {
    apt-get update
    apt-get install -y squid

    local config_file backup_file
    config_file=$(mktemp)
    backup_file="${SQUID_CONFIG}.bak.$(date +%Y%m%d%H%M%S)"

    cat >"$config_file" <<EOF
http_port 0.0.0.0:${SQUID_PORT}
pid_filename ${SQUID_PID}

http_access allow all

cache deny all
access_log stdio:/var/log/squid/access.log
EOF

    squid -k parse -f "$config_file"

    if [[ -f ${SQUID_CONFIG} ]]; then
        cp -a "$SQUID_CONFIG" "$backup_file"
        echo "已备份原配置: ${backup_file}"
    fi
    install -o root -g root -m 0644 "$config_file" "$SQUID_CONFIG"
    rm -f "$config_file"
    echo "Squid 配置已部署到 ${SQUID_CONFIG}。"
}

start_squid() {
    if is_listening; then
        echo "Squid 已在监听 0.0.0.0:${SQUID_PORT}。"
        return 0
    fi

    if has_live_squid; then
        if wait_for_listening; then
            echo "Squid 已在运行，监听 0.0.0.0:${SQUID_PORT}。"
            return 0
        fi
        echo "Squid 进程仍在运行，但端口 ${SQUID_PORT} 未监听；请选 3 重启 Squid。" >&2
        return 1
    fi

    if [[ ! -f ${SQUID_CONFIG} ]]; then
        echo "未找到 ${SQUID_CONFIG}，请先选择 1 安装与配置部署。" >&2
        return 1
    fi

    if has_systemd; then
        systemctl enable squid
        systemctl start squid
    else
        install -d -o proxy -g proxy -m 0755 /run/squid
        squid -sYC -f "$SQUID_CONFIG"
    fi

    if ! wait_for_listening; then
        echo "Squid 启动失败，端口 ${SQUID_PORT} 未监听。" >&2
        return 1
    fi
    echo "Squid 已启动，监听 0.0.0.0:${SQUID_PORT}。"
}

stop_squid() {
    if has_systemd; then
        systemctl stop squid
    elif [[ -f ${SQUID_PID} ]]; then
        local pid
        pid=$(cat "$SQUID_PID")
        kill -TERM "$pid" 2>/dev/null || true
        if ! wait_for_stop "$pid"; then
            echo "等待 Squid 进程 ${pid} 停止超时。" >&2
            return 1
        fi
        rm -f "$SQUID_PID"
    fi
}

restart_squid() {
    if [[ ! -f ${SQUID_CONFIG} ]]; then
        echo "未找到 ${SQUID_CONFIG}，请先选择 1 安装与配置部署。" >&2
        return 1
    fi

    if has_systemd; then
        systemctl enable squid
        systemctl restart squid
    else
        stop_squid
        start_squid
        return
    fi

    if ! wait_for_listening; then
        echo "Squid 重启失败，端口 ${SQUID_PORT} 未监听。" >&2
        return 1
    fi
    echo "Squid 已重启，监听 0.0.0.0:${SQUID_PORT}。"
}

show_status() {
    if has_systemd; then
        systemctl --no-pager --full status squid || true
    else
        if is_listening; then
            echo "Squid 状态: 运行中，监听 0.0.0.0:${SQUID_PORT}。"
        else
            echo "Squid 状态: 未运行。"
        fi
        ps -o pid,user,cmd -C squid 2>/dev/null || true
    fi
}

print_time_every_10_seconds() {
    echo '每 10 秒打印一次当前时间，按 Ctrl+C 停止。'
    while true; do
        date '+%Y-%m-%d %H:%M:%S'
        sleep 10
    done
}

show_menu() {
    echo
    echo '====== Squid 管理菜单 ======'
    echo '1. 安装与配置部署'
    echo '2. 启动'
    echo '3. 重启'
    echo '4. 查看服务状态'
    echo '5. 每 10 秒打印当前时间'
    echo '0. 退出'
    echo '============================'
}

while true; do
    show_menu
    read -r -p '请选择功能 [0-4]: ' choice
    case "$choice" in
        1)
            install_and_configure
            restart_squid
            ;;
        2) start_squid ;;
        3) restart_squid ;;
        4) show_status ;;
        5) print_time_every_10_seconds ;;
        0) echo '已退出。'; exit 0 ;;
        *) echo '无效选项，请输入 0-5。' ;;
    esac
done