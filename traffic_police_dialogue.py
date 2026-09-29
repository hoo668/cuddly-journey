"""警官与司机的自动循环对话示例。"""

import time


def run_dialogue():
    print("自动对话开始（按 Ctrl+C 结束）。")
    try:
        while True:
            print("警官：有没有驾照？")
            time.sleep(1)
            print("司机：有。")
            time.sleep(1)
            print("警官：请出示驾照。")
            time.sleep(1)
            print("司机：算了嘛，警官。")
            print("--------------------")
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n对话已结束。")


if __name__ == "__main__":
    run_dialogue()