export const API='/api';
export async function request(path:string,body?:unknown,method?:string){
 const token=sessionStorage.getItem('token'); const form=body instanceof FormData;
 const response=await fetch(API+path,{method:method||(body?'POST':'GET'),headers:{...(token?{Authorization:'Bearer '+token}:{}),...(!form&&body?{'Content-Type':'application/json'}:{})},body:body?(form?body:JSON.stringify(body)):undefined});
 if(!response.ok){let message;try{const detail=(await response.json()).detail;message=typeof detail==='string'?detail:JSON.stringify(detail)}catch{message=response.statusText}throw new Error(message)}return response.json();
}
export async function download(path:string,name:string){const r=await fetch(API+path,{headers:{Authorization:'Bearer '+sessionStorage.getItem('token')}});if(!r.ok)throw new Error('Download failed');const url=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),5000)}
