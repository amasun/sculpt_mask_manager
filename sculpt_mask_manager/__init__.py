import bpy
import numpy as np
from bpy.types import Panel, Operator, Menu, Header, PropertyGroup
from bpy.props import StringProperty, EnumProperty, BoolProperty, PointerProperty

# --- 核心逻辑：保存遮罩 ---
class SCULPT_OT_mask_save(Operator):
    """Save current sculpt mask as a vertex group"""
    bl_idname = "sculpt.mask_save"
    bl_label = "Save Mask"
    bl_options = {'REGISTER', 'UNDO'}

    mask_name: StringProperty(name="Name", default="MaskGroup")

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Please select a mesh object")
            return {'CANCELLED'}

        mesh = obj.data
        mask_attr = mesh.attributes.get(".sculpt_mask")
        
        if not mask_attr:
            self.report({'WARNING'}, "No valid mask data found")
            return {'CANCELLED'}

        # 确保名称唯一
        base_name = self.mask_name
        unique_name = base_name
        count = 1
        while obj.vertex_groups.get(f"MSK_{unique_name}"):
            unique_name = f"{base_name}_{count:03d}"
            count += 1
        
        vg = obj.vertex_groups.new(name=f"MSK_{unique_name}")
        
        # 性能优化：使用 NumPy 批量读写
        num_verts = len(mesh.vertices)
        mask_values = np.zeros(num_verts, dtype=np.float32)
        mask_attr.data.foreach_get("value", mask_values)
        
        # 顶点组在 Blender 中作为属性处理
        vg_attr = mesh.attributes.get(vg.name)
        if vg_attr:
            vg_attr.data.foreach_set("value", mask_values)
        else:
            # Fallback for edge cases
            for i, val in enumerate(mask_values):
                if val > 0.001:
                    vg.add([i], val, 'REPLACE')
                
        self.report({'INFO'}, f"Mask saved as: {vg.name}")
        return {'FINISHED'}

    def invoke(self, context, event):
        # 弹出属性对话框让用户输入名称
        return context.window_manager.invoke_props_dialog(self)

# --- 核心逻辑：加载遮罩 ---
class SCULPT_OT_mask_load(Operator):
    """Click: Replace | Shift: Add | Ctrl: Subtract"""
    bl_idname = "sculpt.mask_load"
    bl_label = "Load Mask"
    bl_description = "Click: Replace | Shift: Add | Ctrl: Subtract"
    bl_options = {'REGISTER', 'UNDO'}

    group_name: StringProperty()
    mode: EnumProperty(
        name="Blend Mode",
        items=[
            ('REPLACE', "Replace", "Replace current mask", 'ASSET_MANAGER', 0),
            ('ADD', "Add", "Add to current mask", 'ADD', 1),
            ('SUB', "Subtract", "Subtract from current mask", 'REMOVE', 2),
        ],
        default='REPLACE'
    )

    def invoke(self, context, event):
        # 快捷组合键检测
        if event.shift:
            self.mode = 'ADD'
        elif event.ctrl:
            self.mode = 'SUB'
        
        return self.execute(context)

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        vg = obj.vertex_groups.get(self.group_name)
        
        if not vg:
            self.report({'ERROR'}, "Vertex group not found")
            return {'CANCELLED'}

        mask_attr = mesh.attributes.get(".sculpt_mask")
        if not mask_attr:
            mask_attr = mesh.attributes.new(name=".sculpt_mask", type='FLOAT', domain='POINT')
        
        num_verts = len(mesh.vertices)
        saved_weights = np.zeros(num_verts, dtype=np.float32)
        
        # 获取保存的遮罩数据
        vg_attr = mesh.attributes.get(vg.name)
        if vg_attr:
            vg_attr.data.foreach_get("value", saved_weights)
        else:
            for i in range(num_verts):
                try: saved_weights[i] = vg.weight(i)
                except RuntimeError: pass
        
        # 混合逻辑 (使用 NumPy 加速)
        active_mode = self.mode
        if active_mode == 'REPLACE':
            final_weights = saved_weights
        else:
            current_weights = np.zeros(num_verts, dtype=np.float32)
            mask_attr.data.foreach_get("value", current_weights)
            
            if active_mode == 'ADD':
                final_weights = np.clip(current_weights + saved_weights, 0.0, 1.0)
            elif active_mode == 'SUB':
                final_weights = np.clip(current_weights - saved_weights, 0.0, 1.0)
            else:
                final_weights = saved_weights
        
        mask_attr.data.foreach_set("value", final_weights.astype(np.float32))
        mesh.update()
        
        if obj.mode == 'SCULPT':
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.mode_set(mode='SCULPT')
            
        self.report({'INFO'}, f"Mask loaded ({self.mode}): {self.group_name}")
        return {'FINISHED'}

# --- 核心逻辑：清除/反转遮罩 ---
class SCULPT_OT_mask_clear(Operator):
    """Clear all sculpt masks"""
    bl_idname = "sculpt.mask_clear"
    bl_label = "Clear Mask"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH': return {'CANCELLED'}
        
        mesh = obj.data
        mask_attr = mesh.attributes.get(".sculpt_mask")
        if mask_attr:
            num_verts = len(mesh.vertices)
            mask_attr.data.foreach_set("value", np.zeros(num_verts, dtype=np.float32))
            mesh.update()
            if obj.mode == 'SCULPT':
                bpy.ops.object.mode_set(mode='OBJECT')
                bpy.ops.object.mode_set(mode='SCULPT')
        return {'FINISHED'}

class SCULPT_OT_mask_invert(Operator):
    """Invert current sculpt mask"""
    bl_idname = "sculpt.mask_invert"
    bl_label = "Invert Mask"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH': return {'CANCELLED'}
        
        mesh = obj.data
        mask_attr = mesh.attributes.get(".sculpt_mask")
        if mask_attr:
            num_verts = len(mesh.vertices)
            weights = np.zeros(num_verts, dtype=np.float32)
            mask_attr.data.foreach_get("value", weights)
            mask_attr.data.foreach_set("value", 1.0 - weights)
            mesh.update()
            if obj.mode == 'SCULPT':
                bpy.ops.object.mode_set(mode='OBJECT')
                bpy.ops.object.mode_set(mode='SCULPT')
        return {'FINISHED'}

# --- 核心逻辑：删除遮罩 ---
class SCULPT_OT_mask_delete(Operator):
    """Delete saved mask vertex group"""
    bl_idname = "sculpt.mask_delete"
    bl_label = "Delete Mask"
    bl_options = {'REGISTER', 'UNDO'}

    group_name: StringProperty()

    def execute(self, context):
        obj = context.active_object
        vg = obj.vertex_groups.get(self.group_name)
        if vg:
            obj.vertex_groups.remove(vg)
        return {'FINISHED'}

class SCULPT_OT_mask_rename(Operator):
    """Rename selected mask group"""
    bl_idname = "sculpt.mask_rename"
    bl_label = "Rename Mask"
    bl_options = {'REGISTER', 'UNDO'}

    old_name: StringProperty()
    new_name: StringProperty(name="New Name")

    def execute(self, context):
        obj = context.active_object
        vg = obj.vertex_groups.get(self.old_name)
        if vg and self.new_name:
            # 确保新名称也有前缀
            target_name = self.new_name if self.new_name.startswith("MSK_") else f"MSK_{self.new_name}"
            vg.name = target_name
        return {'FINISHED'}

    def invoke(self, context, event):
        self.new_name = self.old_name[4:] if self.old_name.startswith("MSK_") else self.old_name
        return context.window_manager.invoke_props_dialog(self)

# --- UI：通用遮罩列表绘制函数 ---
def draw_mask_list(layout, obj):
    col = layout.column(align=True)
    
    # 顶部功能按钮：合并为一行，减少纵向占用
    row = col.row(align=True)
    row.operator("sculpt.mask_save", icon='ADD', text="Save")
    row.operator("sculpt.mask_invert", icon='UV_SYNC_SELECT', text="Invert")
    row.operator("sculpt.mask_clear", icon='X', text="Clear")
    
    mask_groups = [vg for vg in obj.vertex_groups if vg.name.startswith("MSK_")]
    
    if mask_groups:
        col.separator(factor=0.5)
        # 移除 box 外框，直接平铺列表
        for i, vg in enumerate(mask_groups):
            row = col.row(align=True)
            # 加载按钮
            load = row.operator("sculpt.mask_load", text=vg.name[4:], icon='MOD_MASK')
            load.group_name = vg.name
            load.mode = 'REPLACE'
            
            # 显示管理按钮
            row.operator("sculpt.mask_rename", text="", icon='GREASEPENCIL').old_name = vg.name
            row.operator("sculpt.mask_delete", text="", icon='TRASH').group_name = vg.name

# --- UI：悬浮菜单 (Popover) ---
class SCULPT_MT_mask_popover(Menu):
    bl_label = "" # 移除标题
    bl_idname = "SCULPT_MT_mask_popover"

    def draw(self, context):
        obj = context.active_object
        if obj:
            draw_mask_list(self.layout, obj)

# --- UI：饼状菜单 (Pie Menu) ---
class SCULPT_MT_mask_pie(Menu):
    bl_label = "" # 移除标题，去掉左上角提示
    bl_idname = "SCULPT_MT_mask_pie"

    def draw(self, context):
        pie = self.layout.menu_pie()
        obj = context.active_object
        mask_groups = [vg for vg in obj.vertex_groups if vg.name.startswith("MSK_")]
        
        # 1. 左：反转
        pie.operator("sculpt.mask_invert", icon='UV_SYNC_SELECT', text="Invert")
        # 2. 右：全清
        pie.operator("sculpt.mask_clear", icon='X', text="Clear")
        # 3. 下：保存
        pie.operator("sculpt.mask_save", icon='ADD', text="Save")
        
        # 4. 上：遮罩列表 (包含管理按钮)
        if mask_groups:
            col = pie.column(align=True)
            for vg in mask_groups:
                row = col.row(align=True)
                op = row.operator("sculpt.mask_load", text=vg.name[4:], icon='MOD_MASK')
                op.group_name = vg.name
                op.mode = 'REPLACE'
                
                # 找回管理按钮
                row.operator("sculpt.mask_rename", text="", icon='GREASEPENCIL').old_name = vg.name
                row.operator("sculpt.mask_delete", text="", icon='TRASH').group_name = vg.name
        else:
            pie.separator() # 空位占位

# --- UI：侧边栏面板 ---
class VIEW3D_PT_sculpt_mask_manager(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Sculpt'
    bl_label = "Mask Groups"
    
    @classmethod
    def poll(cls, context):
        return context.sculpt_object is not None

    def draw(self, context):
        draw_mask_list(self.layout, context.active_object)

# --- 注册与快捷键 ---
classes = (
    SCULPT_OT_mask_save,
    SCULPT_OT_mask_load,
    SCULPT_OT_mask_delete,
    SCULPT_OT_mask_rename,
    SCULPT_OT_mask_clear,
    SCULPT_OT_mask_invert,
    SCULPT_MT_mask_popover,
    SCULPT_MT_mask_pie,
    VIEW3D_PT_sculpt_mask_manager,
)

addon_keymaps = []

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    # 注册快捷键 (Alt + M)
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name='Sculpt', space_type='EMPTY')
        kmi = km.keymap_items.new("wm.call_menu_pie", 'M', 'PRESS', alt=True)
        kmi.properties.name = "SCULPT_MT_mask_pie"
        addon_keymaps.append((km, kmi))

def unregister():
    # 移除快捷键
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()
    
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
