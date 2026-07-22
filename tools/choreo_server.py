#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A1Z 12臂编舞器 Web 服务端

用法：
  cd /home/yyyy/桌面/workspace/sport
  python tools/choreo_server.py
  浏览器打开 http://localhost:8765
"""

import asyncio, base64, io, json, math, time, os, sys, threading, webbrowser, queue
from pathlib import Path
import numpy as np
import mujoco
from PIL import Image, ImageDraw
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
import uvicorn

# PyInstaller bundle: add _MEIPASS to PATH so Windows can find bundled ANGLE DLLs
if hasattr(sys, '_MEIPASS'):
    os.environ['PATH'] = sys._MEIPASS + os.pathsep + os.environ.get('PATH', '')

# ─── Main-thread rendering queue ─────────────────────────────────────────────
# All MuJoCo GL operations run on the main thread to satisfy GLFW/WGL/EGL
# thread-affinity requirements on Windows. uvicorn runs in a daemon thread.
_req_q: queue.Queue = queue.Queue()


async def _call_main(fn, *args):
    """Schedule fn(*args) on the main rendering thread; await the result."""
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    _req_q.put((fn, args, fut, loop))
    return await fut


def _rendering_loop():
    """Blocking loop that runs on the main thread and handles all GL calls."""
    _ensure_renderer()          # initialise MuJoCo renderer on main thread
    while True:
        try:
            fn, args, fut, loop = _req_q.get(timeout=0.05)
        except queue.Empty:
            continue
        try:
            result = fn(*args)
            loop.call_soon_threadsafe(fut.set_result, result)
        except Exception as exc:
            loop.call_soon_threadsafe(fut.set_exception, exc)

# ─── 路径（兼容 PyInstaller 打包）────────────────────────────────────────────
def _res(*parts):
    """返回资源文件的绝对路径，打包后从 _MEIPASS 读取"""
    base = Path(sys._MEIPASS) if hasattr(sys, '_MEIPASS') else Path(__file__).parent
    return str(Path(base, *parts))

# 网格文件：开发时在 ../A1Z_Flange/meshes/，打包后在 _MEIPASS/meshes/
if hasattr(sys, '_MEIPASS'):
    MESH_DIR = _res('meshes')
else:
    MESH_DIR = str(Path(__file__).parent.parent / 'A1Z_Flange' / 'meshes')

# 编舞保存目录：始终放在 exe / 脚本旁边（可写）
if hasattr(sys, '_MEIPASS'):
    CHOREO_DIR = Path(sys.executable).parent / 'choreographies'
else:
    CHOREO_DIR = Path(__file__).parent.parent / 'choreographies'

# ─── 常量 ────────────────────────────────────────────────────────────────────
N_ARMS, N_DOF = 12, 6
PI = math.pi

POSE_EQUIL = [0., PI, -PI, 0., 0., 0.]
SY = 1.55
ZT, ZM, ZB = 3.20, 1.65, 0.10
ARM_POS = [
    (-2*SY,ZT),(-SY,ZT),(0,ZT),(SY,ZT),(2*SY,ZT),
    (-1.5*SY,ZM),(-0.5*SY,ZM),(0.5*SY,ZM),(1.5*SY,ZM),
    (-SY,ZB),(0,ZB),(SY,ZB),
]
ARM_ROW = [0]*5 + [1]*4 + [2]*3

# ─── MJCF 生成 ────────────────────────────────────────────────────────────────
_BC = ["0.68 0.52 0.38 1","0.38 0.50 0.70 1","0.36 0.64 0.50 1"]
_LC = ["0.74 0.58 0.44 1","0.44 0.58 0.76 1","0.42 0.70 0.56 1"]
_EC = ["1.00 0.85 0.10 0.95","0.10 0.90 0.90 0.95","0.90 0.18 0.85 0.95"]

def _arm_xml(i, y, z):
    n, r = i+1, ARM_ROW[i]
    b, l, e = _BC[r], _LC[r], _EC[r]
    return (
        f'    <body name="base_{n}" pos="0 {y:.4f} {z:.4f}" euler="0 1.5708 0">\n'
        f'      <geom type="mesh" mesh="base_link" rgba="{b}"/>\n'
        f'      <body name="link1_{n}" pos="0 0 0.075">\n'
        f'        <joint name="j1_{n}" type="hinge" axis="0 0 1" range="-2.094 2.094"/>\n'
        f'        <geom type="mesh" mesh="arm_link1" rgba="{l}"/>\n'
        f'        <body name="link2_{n}" pos="0.02 0 0.043">\n'
        f'          <joint name="j2_{n}" type="hinge" axis="0 1 0" range="-3.34 3.34"/>\n'
        f'          <geom type="mesh" mesh="arm_link2" rgba="{l}"/>\n'
        f'          <body name="link3_{n}" pos="-0.264 0 0">\n'
        f'            <joint name="j3_{n}" type="hinge" axis="0 1 0" range="-3.34 0.1"/>\n'
        f'            <geom type="mesh" mesh="arm_link3" rgba="{l}"/>\n'
        f'            <body name="link4_{n}" pos="0.245 0 0.06">\n'
        f'              <joint name="j4_{n}" type="hinge" axis="0 1 0" range="-1.309 1.309"/>\n'
        f'              <geom type="mesh" mesh="arm_link4" rgba="{l}"/>\n'
        f'              <body name="link5_{n}" pos="0.074 0 0.042">\n'
        f'                <joint name="j5_{n}" type="hinge" axis="0 0 1" range="-1.484 1.484"/>\n'
        f'                <geom type="mesh" mesh="arm_link5" rgba="{l}"/>\n'
        f'                <body name="link6_{n}" pos="0.0235 0 -0.042">\n'
        f'                  <joint name="j6_{n}" type="hinge" axis="1 0 0" range="-2.007 2.007"/>\n'
        f'                  <geom type="mesh" mesh="arm_link6" rgba="{l}"/>\n'
        f'                  <geom type="sphere" size="0.014" pos="0.12 0 0" rgba="{e}"/>\n'
        f'                  <site name="ee_{n}" pos="0.12 0 0" size="0.003"/>\n'
        f'                </body></body></body></body></body></body></body>'
    )

def _act_xml(i):
    n = i+1
    return "\n".join([
        f'    <position name="a1_{n}" joint="j1_{n}" kp="60" kv="4"  ctrlrange="-2.094 2.094"/>',
        f'    <position name="a2_{n}" joint="j2_{n}" kp="90" kv="5"  ctrlrange="-3.34  3.34"/>',
        f'    <position name="a3_{n}" joint="j3_{n}" kp="70" kv="4"  ctrlrange="-3.34  0.1"/>',
        f'    <position name="a4_{n}" joint="j4_{n}" kp="35" kv="2"  ctrlrange="-1.309 1.309"/>',
        f'    <position name="a5_{n}" joint="j5_{n}" kp="18" kv="1"  ctrlrange="-1.484 1.484"/>',
        f'    <position name="a6_{n}" joint="j6_{n}" kp="18" kv="1"  ctrlrange="-2.007 2.007"/>',
    ])

def _build_mjcf():
    wy = 2*SY+0.22; wz_c = (ZT+ZB)/2; wz_h = (ZT-ZB)/2+0.30
    plates = "\n".join(
        f'    <geom name="plate_{i+1}" type="box" size="0.006 0.063 0.063"'
        f' pos="-0.082 {y:.4f} {z:.4f}" rgba="0.26 0.26 0.30 1"/>'
        for i,(y,z) in enumerate(ARM_POS))
    arms = "\n".join(_arm_xml(i,y,z) for i,(y,z) in enumerate(ARM_POS))
    acts = "\n".join(_act_xml(i) for i in range(N_ARMS))
    return f"""<mujoco model="A1Z_12arm">
  <compiler angle="radian" meshdir="{MESH_DIR}"/>
  <option timestep="0.004" gravity="0 0 -9.81" integrator="RK4"/>
  <visual>
    <rgba haze="0.15 0.20 0.30 1"/>
    <quality shadowsize="2048" offsamples="4"/>
    <global offwidth="800" offheight="600"/>
    <headlight diffuse="0.9 0.9 0.9" ambient="0.5 0.5 0.5" specular="0.3 0.3 0.3"/>
  </visual>
  <default>
    <joint damping="6.0" armature="0.01" frictionloss="0.3"/>
    <geom contype="0" conaffinity="0"/>
  </default>
  <asset>
    <mesh name="base_link" file="base_link.STL"/>
    <mesh name="arm_link1" file="arm_link1.STL"/>
    <mesh name="arm_link2" file="arm_link2.STL"/>
    <mesh name="arm_link3" file="arm_link3.STL"/>
    <mesh name="arm_link4" file="arm_link4.STL"/>
    <mesh name="arm_link5" file="arm_link5.STL"/>
    <mesh name="arm_link6" file="arm_link6.STL"/>
    <texture name="ft" type="2d" builtin="checker" width="512" height="512"
             rgb1="0.05 0.09 0.16" rgb2="0.08 0.13 0.22"/>
    <material name="floor" texture="ft" texrepeat="10 10"/>
    <texture name="wt" type="2d" builtin="flat" width="4" height="4" rgb1="0.76 0.70 0.62"/>
    <material name="wall" texture="wt"/>
  </asset>
  <worldbody>
    <light name="top"  pos="3 0 6"   dir="-0.5 0 -1" diffuse="0.8 0.8 0.8" specular="0.2 0.2 0.2" castshadow="false"/>
    <light name="left" pos="2 -4 4"  dir="-0.3 0.8 -0.8" diffuse="0.4 0.5 0.6" specular="0.1 0.1 0.1" castshadow="false"/>
    <light name="fill" pos="2  4 4"  dir="-0.3 -0.8 -0.8" diffuse="0.4 0.4 0.5" specular="0.0 0.0 0.0" castshadow="false"/>
    <geom name="floor" type="plane" size="8 8 0.01" pos="0 0 -0.85" material="floor"/>
    <geom name="wall" type="box" size="0.025 {wy:.4f} {wz_h:.4f}"
          pos="-0.125 0 {wz_c:.4f}" material="wall"/>
{plates}
{arms}
  </worldbody>
  <actuator>
{acts}
  </actuator>
</mujoco>"""


# ─── 仿真状态（单例）────────────────────────────────────────────────────────────
class SimState:
    def __init__(self):
        self.model     = mujoco.MjModel.from_xml_string(_build_mjcf())
        self.data      = mujoco.MjData(self.model)
        # renderer 延迟到工作线程里初始化，避免 EGL 跨线程问题
        self.renderer  = None
        self.cam       = mujoco.MjvCamera()
        self.scene_opt = mujoco.MjvOption()
        self.cam.azimuth, self.cam.elevation = 180.0, -15.0
        self.cam.distance  = 9.0
        self.cam.lookat[:] = [0.5, 0.0, 1.65]

        init = np.tile(POSE_EQUIL, N_ARMS)
        self.data.qpos[:] = init
        self.data.ctrl[:] = init
        mujoco.mj_forward(self.model, self.data)

        self.live_poses = np.tile(POSE_EQUIL, (N_ARMS, 1))
        self.sequences  = [[] for _ in range(N_ARMS)]
        self.is_playing = False
        self.play_speed = 1.0
        self.play_time  = 0.0
        self._play_st   = None


sim = SimState()

# ─── GL backend auto-detection ───────────────────────────────────────────────
_RENDER_FAILED = False


def _make_placeholder() -> str:
    """Return a base64 JPEG placeholder when rendering is unavailable."""
    img  = Image.new('RGB', (800, 600), (13, 16, 24))
    draw = ImageDraw.Draw(img)
    draw.rectangle([150, 230, 650, 370], fill=(30, 36, 56))
    draw.text((400, 270), '3D view unavailable', fill=(140, 160, 200), anchor='mm')
    draw.text((400, 305), 'No OpenGL backend could be initialised.', fill=(90, 110, 150), anchor='mm')
    draw.text((400, 335), 'Choreography editing still works normally.', fill=(70, 90, 130), anchor='mm')
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=70)
    return base64.b64encode(buf.getvalue()).decode()


_PLACEHOLDER = None


def _angle_egl_path() -> str | None:
    """On Windows, locate Edge's ANGLE DLLs so EGL backend can work."""
    import glob, platform
    if platform.system() != 'Windows':
        return None
    patterns = [
        r'C:\Program Files (x86)\Microsoft\Edge\Application\*',
        r'C:\Program Files\Microsoft\Edge\Application\*',
    ]
    for pat in patterns:
        dirs = sorted(glob.glob(pat), reverse=True)
        if dirs:
            return dirs[0]
    return None


def _ensure_renderer():
    """Try GL backends in order; fall back to placeholder on total failure."""
    global _RENDER_FAILED, _PLACEHOLDER
    if sim.renderer is not None or _RENDER_FAILED:
        return

    import platform
    is_win = platform.system() == 'Windows'

    # On Windows: EGL via ANGLE (no main-thread constraint) first,
    # then default GLFW (may fail from worker thread), then osmesa.
    # On Linux: default (EGL/GLFW) first, then osmesa.
    backends = (
        [('egl', 'EGL (ANGLE/DirectX)'), (None, 'Default (GLFW)'), ('osmesa', 'OSMesa')]
        if is_win else
        [(None, 'Default (EGL/GLFW)'), ('osmesa', 'OSMesa')]
    )

    # For Windows EGL, add Edge ANGLE DLL directory to PATH
    angle_dir = _angle_egl_path()
    if angle_dir:
        os.environ['PATH'] = angle_dir + os.pathsep + os.environ.get('PATH', '')
        print(f'[render] ANGLE path: {angle_dir}')

    for env_val, name in backends:
        try:
            if env_val is None:
                os.environ.pop('MUJOCO_GL', None)
            else:
                os.environ['MUJOCO_GL'] = env_val
            sim.renderer = mujoco.Renderer(sim.model, height=600, width=800)
            print(f'[render] backend: {name}')
            return
        except Exception as exc:
            print(f'[render] {name} failed: {exc}')
            sim.renderer = None

    _RENDER_FAILED = True
    _PLACEHOLDER   = _make_placeholder()
    print('[render] all backends failed - serving placeholder')


def _minjerk_step(q0, q1, tau):
    s = 10*tau**3 - 15*tau**4 + 6*tau**5
    return np.array(q0) + s*(np.array(q1)-np.array(q0))


def _do_sim_step():
    """仿真步进 + 播放逻辑（同步，在 executor 中调用）"""
    dt = 0.033 * sim.play_speed

    if sim.is_playing and sim._play_st:
        all_done = True
        for i, st in enumerate(sim._play_st):
            blks = sim.sequences[i]
            if not blks:
                continue
            bi = st["bi"]
            if bi >= len(blks):
                continue
            all_done = False
            st["elapsed"] += dt
            blk = blks[bi]
            tau = min(1.0, st["elapsed"] / max(blk["duration"], 0.001))
            sim.live_poses[i] = _minjerk_step(st["q0"], blk["pose"], tau)
            if st["elapsed"] >= blk["duration"]:
                st["bi"]     += 1
                st["elapsed"] = 0.0
                if st["bi"] < len(blks):
                    st["q0"] = blk["pose"]
        if all_done:
            sim.is_playing = False
        st0 = sim._play_st[0]
        blks0 = sim.sequences[0]
        if blks0 and st0["bi"] < len(blks0):
            sim.play_time = (sum(b["duration"] for b in blks0[:st0["bi"]])
                             + st0["elapsed"])

    for i in range(N_ARMS):
        sim.data.ctrl[i*N_DOF:(i+1)*N_DOF] = sim.live_poses[i]
    mujoco.mj_step(sim.model, sim.data)


def _render_jpeg():
    """Render current scene; returns base64 JPEG string."""
    _ensure_renderer()
    if sim.renderer is None:
        return _PLACEHOLDER or _make_placeholder()
    sim.renderer.update_scene(sim.data, camera=sim.cam,
                              scene_option=sim.scene_opt)
    pixels = sim.renderer.render()
    img = Image.fromarray(pixels)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=82)
    return base64.b64encode(buf.getvalue()).decode()


def _step_and_render():
    """Sim step + render, always called on the main thread via _req_q."""
    _do_sim_step()
    return _render_jpeg()


def _handle_cmd(msg: dict):
    """处理来自客户端的命令（同步）"""
    t = msg.get("type", "")
    if t == "set_pose":
        sim.live_poses[msg["arm"]] = np.array(msg["pose"], dtype=float)
    elif t == "set_cam":
        sim.cam.azimuth   = msg.get("az",   sim.cam.azimuth)
        sim.cam.elevation = msg.get("el",   sim.cam.elevation)
        sim.cam.distance  = max(2.0, msg.get("dist", sim.cam.distance))
    elif t == "play":
        sim.sequences  = msg.get("sequences", [[] for _ in range(N_ARMS)])
        sim.play_speed = float(msg.get("speed", 1.0))
        sim._play_st   = [{"bi": 0, "elapsed": 0.0,
                           "q0": sim.live_poses[i].tolist()}
                          for i in range(N_ARMS)]
        sim.is_playing = True
        sim.play_time  = 0.0
    elif t == "stop":
        sim.is_playing = False
    elif t == "seek":
        sim.is_playing = False
        sim.play_time  = 0.0
        for i in range(N_ARMS):
            blks = sim.sequences[i]
            sim.live_poses[i] = (np.array(blks[0]["pose"])
                                 if blks else np.array(POSE_EQUIL))
    elif t == "set_speed":
        sim.play_speed = float(msg.get("speed", 1.0))
    elif t == "update_sequences":
        sim.sequences = msg.get("sequences", [[] for _ in range(N_ARMS)])
    elif t == "save":
        CHOREO_DIR.mkdir(parents=True, exist_ok=True)
        fname = msg.get("name", "untitled") + ".json"
        data  = msg.get("data", {})
        (CHOREO_DIR / fname).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── FastAPI 应用 ─────────────────────────────────────────────────────────────
app = FastAPI()

INDEX_HTML = Path(_res('static', 'index.html'))


@app.get("/")
async def get_index():
    return FileResponse(INDEX_HTML)


@app.get("/list_saves")
async def list_saves():
    CHOREO_DIR.mkdir(parents=True, exist_ok=True)
    files = [p.stem for p in sorted(CHOREO_DIR.glob("*.json"))]
    return {"files": files}


@app.get("/load/{name}")
async def load_file(name: str):
    path = CHOREO_DIR / (name + ".json")
    if not path.exists():
        return {"error": "not found"}
    return json.loads(path.read_text(encoding="utf-8"))


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()

    async def _send():
        while True:
            try:
                frame = await _call_main(_step_and_render)
                await websocket.send_json({
                    "type": "frame",
                    "data": frame,
                    "playing": sim.is_playing,
                    "time": round(sim.play_time, 2),
                })
            except Exception:
                break
            await asyncio.sleep(0.033)

    async def _recv():
        try:
            async for raw in websocket.iter_text():
                try:
                    msg = json.loads(raw)
                    await _call_main(_handle_cmd, msg)
                except Exception:
                    pass
        except WebSocketDisconnect:
            pass

    await asyncio.gather(_send(), _recv())


if __name__ == "__main__":
    PORT = 8765
    print("=" * 55)
    print("  A1Z Choreography Editor")
    print(f"  http://localhost:{PORT}")
    print("=" * 55)
    CHOREO_DIR.mkdir(parents=True, exist_ok=True)

    def _open_browser():
        time.sleep(1.8)
        webbrowser.open(f'http://localhost:{PORT}')

    threading.Thread(target=_open_browser, daemon=True).start()

    # uvicorn runs in a daemon thread; main thread stays for GL rendering
    threading.Thread(
        target=lambda: uvicorn.run(app, host='127.0.0.1', port=PORT, log_level='warning'),
        daemon=True,
    ).start()

    _rendering_loop()   # blocks main thread forever
