-- Injected into patched chunks; the game can use multiple script environments.
do
    if not _G.cpcmodloader then
        local api = {
            version = "0.1.0",
            modules = {},
            loaded = {},
            loading = {},
        }
        local native_require = _G.require
        function api.log(message)
            print("[cpcmodloader] " .. tostring(message))
        end
        function api.require(name)
            if api.loaded[name] ~= nil then return api.loaded[name] end
            local factory = api.modules[name]
            if not factory then
                if native_require then return native_require(name) end
                error("cpcmodloader: module not registered: " .. tostring(name), 2)
            end
            if api.loading[name] then
                error("cpcmodloader: circular module dependency: " .. name, 2)
            end
            api.loading[name] = true
            local ok, result = pcall(factory, name)
            api.loading[name] = nil
            if not ok then error(result, 2) end
            if result == nil then result = true end
            api.loaded[name] = result
            return result
        end
        function api.preload(name, factory)
            if api.modules[name] then return end
            api.modules[name] = factory
            if _G.package and _G.package.preload then
                _G.package.preload[name] = function() return api.require(name) end
            end
        end
        _G.cpcmodloader = api
        if not native_require then _G.require = api.require end
    end
end
