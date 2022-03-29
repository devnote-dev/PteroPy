from aiohttp import ClientSession
from json import dumps
from time import time
from typing import Callable, Optional
from .events import EventManager
from .errors import PteroAPIError, RequestError, ValidationError


class RequestManager(EventManager):
    def __init__(self, _type: str, domain: str, auth: str) -> None:
        super().__init__()
        self._type = _type
        self.domain = domain
        self.auth = auth
        self.suspended = False
        self.ping: float = -1.0
    
    def get_headers(self) -> dict[str, str]:
        if self._type is None:
            raise TypeError('api type is required for requests')
        
        if self.auth is None:
            raise TypeError('missing authorization for requests')
        
        return {
            'User-Agent': '%s Pytero v0.1.0' % self._type,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': 'Bearer %s' % self.auth}
    
    def _validate_query(self, query: dict[str,]) -> str:
        res = []
        
        if p := query.get('page'):
            if 1 < p > 50:
                raise ValidationError('page number must be between 1 and 50')
            
            res.append('page=%d' % p)
        
        if p := query.get('per_page'):
            if 1 < p > 100:
                raise ValidationError('per_page number must be between 1 and 100')
            
            res.append('per_page=%d' % p)
        
        if p := query.get('filter'):
            res.append('filter[%s]=%s' % p)
        
        if p := query.get('include'):
            p = list(filter(lambda i: i, p))
            if len(p):
                res.append('include=%s' % ','.join(p))
        
        if p := query.get('sort'):
            res.append('sort=%s' % p)
        
        if len(res) == 0:
            return ''
        
        return '?' + res[0] + ('&' + '&'.join(res[1:]) if len(res) > 1 else '')
    
    async def _make(self, path: str, method: str, **params):
        if method not in ('GET', 'POST', 'PATCH', 'PUT', 'DELETE'):
            raise ValueError("invalid http method '%s'" % method)
        
        body: Optional[str] = None
        if params is not None:
            if p := params.get('raw'):
                await self.__debug('sending raw byte payload')
                body = p
            else:
                copy = dict(params)
                for key in ('page', 'per_page', 'filter', 'include', 'sort'):
                    copy.pop(key, None)
                
                if len(copy):
                    await self.__debug('sending json payload')
                    body = dumps(copy)
        
        query = self._validate_query(params)
        url = '%s/api/%s%s%s' % (self.domain, self._type.lower(), path, query)
        
        await self.__debug('attempting to start session')
        async with ClientSession() as session:
            await self.__debug('attemping to perform request to %s' % url)
            
            start = time()
            async with getattr(session, method.lower())(
                    url,
                    data=body,
                    headers=self.get_headers()) as response:
                self.ping = time() - start
                
                await self.__debug('ensuring session close before continuing')
                await session.close()
                await self.__debug('received status: %d' % response.status)
                
                if response.status == 204:
                    return None
                
                if response.status in (200, 201):
                    data: dict[str,] = await response.json()
                    try:
                        await super().emit_event('receive', data)
                    except:
                        pass
                    
                    return data
                
                if 400 <= response.status < 500:
                    err: dict[str,] = await response.json()
                    raise PteroAPIError(err['errors'][0]['code'], err)
                
                raise RequestError(
                    'pterodactyl api returned an invalid or unacceptable'
                    ' response (status: %d)' % response.status)
    
    async def rget(self, path: str, **data):
        return await self._make(path, 'GET', **data)
    
    async def rpost(self, path: str, **data):
        return await self._make(path, 'POST', **data)
    
    async def rpatch(self, path: str, **data):
        return await self._make(path, 'PATCH', **data)
    
    async def rput(self, path: str, **data):
        return await self._make(path, 'PUT', **data)
    
    async def rdelete(self, path: str):
        return await self._make(path, 'DELETE')
    
    async def __debug(self, message: str) -> None:
        try:
            await super().emit_event('debug', '[debug] '+ message)
        except:
            pass
    
    def on_receive(
        self,
        func: Callable[[dict[str,]], None]
    ) -> Callable[[dict[str,]], None]:
        super().add_event_slot('receive', func)
        return func
    
    def on_debug(self, func: Callable[[str], None]) -> Callable[[str], None]:
        super().add_event_slot('debug', func)
        return func
