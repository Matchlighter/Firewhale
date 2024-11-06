#!lua name=firewhale_ips

local function hgetall(hash_key)
    local flat_map = redis.call('HGETALL', hash_key)
    if #flat_map == 0 then
        return nil
    end
    local result = {}
    for i = 1, #flat_map, 2 do
        result[flat_map[i]] = flat_map[i + 1]
    end
    return result
end

local hmset = function (key, dict)
    if next(dict) == nil then return nil end
    local bulk = {}
    for k, v in pairs(dict) do
        table.insert(bulk, k)
        table.insert(bulk, v)
    end
    return redis.call('HMSET', key, unpack(bulk))
end

local sets = {
    'service',
    'container',
    'node'
}

local function set_ip(keys, argv)
    -- IP, Service, Container, Node
    local ip = keys[1]
    local ipkey = 'ip:' .. ip
    local existing = hgetall(ipkey)
    local current = {
        service = argv[1],
        container = argv[2],
        node = argv[3]
    }

    local same = true
    for _, set in ipairs(sets) do
        if not existing then
            same = false
        elseif existing[set] ~= argv[set] then
            same = false
            -- If different, remove frome old sets
            redis.call('SREM', set .. ':' .. existing[set] .. ":ips", ip)
        end
        -- Add to new sets
        redis.call('SADD', set .. ':' .. current[set] .. ":ips", ip)
    end

    -- If same, done
    if same then
        return false
    end

    hmset(ipkey, current)

    if existing and existing.service ~= current.service then
        -- Notify "remove" from old service
        redis.call('PUBLISH', existing.service, ip)
    end

    redis.call('PUBLISH', "service:" .. current.service, ip)

    return true
end

local function _remove_ip(ip, ekey, expectation)
    local ipkey = 'ip:' .. ip

    local iphash = hgetall(ipkey)
    if not iphash then
        return false
    end

    if ekey and iphash[ekey] ~= expectation then
        return false
    end

    for _, set in ipairs(sets) do
        redis.call('SREM', set .. ':' .. iphash[set] .. ":ips", ip)
    end

    redis.call('DEL', ipkey)
    redis.call('PUBLISH', "service:" .. iphash.service, ip)

    return true
end

local function remove_ip(keys, argv)
    -- IP, Expectation Key, Expectation Value
    return _remove_ip(keys[1], argv[1], argv[2])
end

local function remove_ips_by(keys, argv)
    -- Set Key, Set Type
    local rset = keys[1]
    local stype = argv[1]
    local ips = redis.call('SMEMBERS', stype .. ':' .. rset .. ":ips")

    local removed_ips = {}
    for _, ip in ipairs(ips) do
        if _remove_ip(ip, stype, rset) then
            table.insert(removed_ips, ip)
        end
    end

    return removed_ips
end

redis.register_function('set_ip', set_ip)
redis.register_function('rm_ip', remove_ip)
redis.register_function('rm_ips_by', remove_ips_by)
