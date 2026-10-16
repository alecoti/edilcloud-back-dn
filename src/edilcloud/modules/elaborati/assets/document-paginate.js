() => {
  const first=document.querySelector('.sheet');
  const body=first.querySelector('.body');
  // Pair adjacent photographs explicitly marked for comparison.
  for(const figure of [...body.querySelectorAll(':scope > figure.half')]){
    const sibling=figure.nextElementSibling;
    if(figure.parentElement!==body||!sibling?.matches('figure.half'))continue;
    const pair=document.createElement('div');pair.className='photo-grid';
    figure.before(pair);pair.append(figure,sibling);
  }
  const blocks=[...body.children];body.replaceChildren();
  const proto=first.cloneNode(true);
  const title=first.querySelector('h1').textContent;
  let current=first;
  const fits=()=>current.querySelector('main').getBoundingClientRect().bottom+12<=current.querySelector('footer').getBoundingClientRect().top;
  const next=()=>{
    const sheet=proto.cloneNode(true);
    const intro=sheet.querySelector('.intro');intro.replaceChildren();
    const running=document.createElement('p');running.className='running';running.textContent=proto.querySelector('footer span').textContent;
    const heading=document.createElement('h1');heading.className='continuation';heading.textContent=title;
    intro.append(running,heading);current.after(sheet);current=sheet;
  };
  let pending=[];
  for(let blockIndex=0;blockIndex<blocks.length;blockIndex++){
    const block=blocks[blockIndex];
    if(/^H[123]$/.test(block.tagName)){pending.push(block);continue;}
    // Source-register metadata belongs with its title and first table row.
    // Keeping only H2 with the metadata stranded both above a page break.
    if(pending.length&&block.matches('p.closing')&&blocks[blockIndex+1]?.tagName==='TABLE'){
      pending.push(block);continue;
    }
    if(block.tagName==='TABLE'){
      const rows=[...block.querySelector('tbody').children];
      block.querySelector('tbody').replaceChildren();
      let target=block;
      let targetBody=current.querySelector('.body');
      pending.forEach(el=>targetBody.append(el));targetBody.append(target);
      for(const row of rows){
        target.querySelector('tbody').append(row);
        if(!fits()){
          row.remove();const empty=target.querySelector('tbody').children.length===0;
          if(empty){target.remove();pending.forEach(el=>el.remove());}
          next();targetBody=current.querySelector('.body');
          if(empty)pending.forEach(el=>targetBody.append(el));
          target=block.cloneNode(true);target.querySelector('tbody').replaceChildren();
          targetBody.append(target);target.querySelector('tbody').append(row);
          if(!fits())throw Error('Una riga della tabella supera lo spazio di una pagina: suddividere il contenuto della riga.');
        }
      }
      pending=[];continue;
    }
    const target=current.querySelector('.body');pending.forEach(el=>target.append(el));target.append(block);
    if(!fits()){
      block.remove();pending.forEach(el=>el.remove());next();
      const target=current.querySelector('.body');pending.forEach(el=>target.append(el));target.append(block);
      if(!fits())throw Error('Un blocco supera lo spazio della pagina: suddividerlo nell’editor.');
    }
    pending=[];
  }
  if(pending.length)throw Error('Titolo privo di contenuto alla fine del documento.');
  const sheets=[...document.querySelectorAll('.sheet')];
  sheets.forEach((sheet,i)=>sheet.querySelector('footer span:last-child').textContent=`${i+1} / ${sheets.length}`);
  const overflow=sheets.map((sheet,i)=>({page:i+1,overflow:Math.max(0,sheet.querySelector('main').getBoundingClientRect().bottom+12-sheet.querySelector('footer').getBoundingClientRect().top)}));
  if(overflow.some(page=>page.overflow>0))throw Error('Il contenuto supera il margine del documento.');
  return {pages:sheets.length,overflow};
}
