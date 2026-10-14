import {beforeEach,describe,it,expect,vi} from 'vitest';
import {request} from './api';
describe('Operations API boundary',()=>{
 beforeEach(()=>{vi.stubGlobal('sessionStorage',{getItem:()=> 'local-test-token'});vi.stubGlobal('fetch',vi.fn())});
 it('authenticates log ingestion without modifying its text',async()=>{vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>({inserted:1})} as Response);const text='2026-10-14T10:00:00Z ERROR checkout-api database connection timeout';await request('/logs/paste',{text});const options=vi.mocked(fetch).mock.calls[0][1];expect(options?.headers).toEqual({Authorization:'Bearer local-test-token','Content-Type':'application/json'});expect(JSON.parse(String(options?.body)).text).toBe(text)});
 it('does not override upload MIME boundaries',async()=>{vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>({})} as Response);const form=new FormData();form.set('service','checkout-api');await request('/logs/upload',form);expect(vi.mocked(fetch).mock.calls[0][1]?.headers).toEqual({Authorization:'Bearer local-test-token'})});
 it('shows rejected lifecycle transitions',async()=>{vi.mocked(fetch).mockResolvedValue({ok:false,json:async()=>({detail:'Missing resolution validation'})} as Response);await expect(request('/incidents/id/status',{status:'CLOSED'},'PATCH')).rejects.toThrow('Missing resolution validation')});
 it('uses GET for read-only investigation',async()=>{vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>({})} as Response);await request('/incidents/id');expect(vi.mocked(fetch).mock.calls[0][1]?.method).toBe('GET')});
});
