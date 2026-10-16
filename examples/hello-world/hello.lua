local M = {}
function M.hello(message)
    _G.cpcmodloader.log(message)
end
return M
