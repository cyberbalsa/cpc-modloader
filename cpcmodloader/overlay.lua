-- Attach the label to this menu so it is removed when the menu closes.
do
    local original_create = create
    function create(menu)
        original_create(menu)
        setTimeout(menu, 0.0, function()
            loadModels("assets/models/cpcmodloader_overlay.glb", false, false)
            local overlay = createChild(menu, "cpcmodloader_overlay")
            setComponents(overlay, {
                Transform(),
                RenderModel {
                    modelName = "CPCModloaderOverlay",
                    bWriteDepth = false,
                    zIndex = 100,
                },
                CustomShader {
                    vertexShaderPath = "shaders/cpcmodloader_overlay.vert",
                    fragmentShaderPath = "shaders/cpcmodloader_overlay.frag",
                    uniformsFloat = { cpcScale = gameSettings.graphics.uiScale },
                },
            })
            setUpdateFunction(overlay, 0.25, function()
                component.CustomShader.getFor(overlay).uniformsFloat.cpcScale = gameSettings.graphics.uiScale
            end)
            onEvent("OnGameGoodbye", function()
                if valid(overlay) then destroyEntity(overlay) end
            end)
            _G.cpcmodloader.log(_G.cpcmodloader.status)
        end)
    end
end
